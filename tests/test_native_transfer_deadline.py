"""Real HTTP streaming deadline regressions, with a bounded loopback peer."""

import json
import struct
import threading
import time
import tomllib
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest

from comfy_prompt_cli import native_backend


def test_artifact_trace_events_use_the_exercised_httpcore_version():
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert "httpcore==1.0.9" in project["project"]["dependencies"]


@contextmanager
def artifact_server(mode):
    stopped = threading.Event()
    disconnected = threading.Event()
    calls = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format, *args):
            pass

        def reply(self, body):
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            calls.append(self.path)
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.path == "/upload/image":
                self.reply({"name": "input.png"})
            elif self.path == "/prompt":
                self.reply({"prompt_id": "job"})
            else:
                self.send_error(404)

        def do_GET(self):
            path = urlsplit(self.path).path
            calls.append(path)
            if path == "/held":
                self.send_response(200)
                self.send_header("Content-Length", "1")
                self.end_headers()
                if not stopped.wait(0.8):
                    self.wfile.write(b"x")
                    self.wfile.flush()
                return
            if path == "/history/job":
                # The artifact must get the remainder, not a fresh budget.
                stopped.wait(0.15)
                self.reply(
                    {
                        "job": {
                            "status": {"completed": True},
                            "outputs": {
                                "save": {
                                    "3d": [{"filename": "mesh.glb", "type": "output"}]
                                }
                            },
                        }
                    }
                )
                return
            if path != "/view":
                self.send_error(404)
                return
            try:
                self.send_response(200)
                self.send_header("Content-Length", "76")
                if mode.startswith("headers-"):
                    self.flush_headers()
                    count = 6 if mode == "headers-then-body" else 32
                    for index in range(count):
                        if mode == "headers-late-stall" and index == 8:
                            self.connection.settimeout(2)
                            if self.connection.recv(1) == b"":
                                disconnected.set()
                                return
                        if stopped.wait(0.04):
                            return
                        self.wfile.write(f"X-Progress-{index}: 1\r\n".encode())
                        self.wfile.flush()
                self.end_headers()
                self.wfile.write(struct.pack("<4sII", b"glTF", 2, 76))
                self.wfile.flush()
                for index in range(32):
                    if mode == "late-stall" and index == 8:
                        # A timeout captured at response-open is now too long.
                        self.connection.settimeout(2)
                        if self.connection.recv(1) == b"":
                            disconnected.set()
                            return
                    if stopped.wait(0.04):
                        return
                    self.wfile.write(b"xx")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                disconnected.set()
            except TimeoutError:
                # Bounded peer fuse; old code can still finish its GLB.
                self.wfile.write(b"xx" * (32 - index))
                self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.02}
    )
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", disconnected, calls
    finally:
        stopped.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
        assert not worker.is_alive()


@pytest.mark.parametrize(
    "mode",
    [
        "continuous",
        "late-stall",
        "headers-continuous",
        "headers-late-stall",
        "headers-then-body",
    ],
)
def test_generate_deadline_covers_real_artifact_stream(tmp_path, mode):
    source = tmp_path / "input.png"
    source.write_bytes(b"fixture")
    out = tmp_path / "out"
    out.mkdir()
    protected = out / "existing.glb"
    protected.write_bytes(b"preserve")
    with (
        artifact_server(mode) as (url, disconnected, calls),
        httpx.Client(base_url=url, timeout=5, trust_env=False) as client,
    ):
        started = time.monotonic()
        with pytest.raises(TimeoutError, match="timed out"):
            native_backend.generate(client, source, out, validate=False, timeout=0.6)
        elapsed = time.monotonic() - started
        assert 0.5 <= elapsed < 0.85, f"deadline exceeded: {elapsed:.3f}s"
        assert list(out.iterdir()) == [protected], "partial artifact survived timeout"
        assert protected.read_bytes() == b"preserve"
        assert disconnected.wait(0.3), "response socket was not closed before teardown"
        assert calls == ["/upload/image", "/prompt", "/history/job", "/view"]
        assert not any(isinstance(t, threading.Timer) for t in threading.enumerate())


@pytest.mark.parametrize("warm", [False, True], ids=["fresh", "pooled"])
def test_download_header_deadline_preserves_other_client_connections(tmp_path, warm):
    # Keep a separate response active in the same pool. Its body must remain
    # readable after the artifact socket is interrupted; never close the client.
    with (
        artifact_server("headers-continuous") as (url, disconnected, calls),
        httpx.Client(base_url=url, timeout=5, trust_env=False) as client,
        client.stream("GET", "/held") as unrelated,
    ):
        if warm:
            client.get("/history/job").raise_for_status()
        started = time.monotonic()
        with pytest.raises(TimeoutError, match="timed out"):
            native_backend._download(
                client,
                [{"filename": "mesh.glb", "type": "output"}],
                tmp_path,
                deadline=started + 0.2,
            )
        assert time.monotonic() - started < 0.5
        assert disconnected.wait(0.3)
        assert not list(tmp_path.iterdir())
        assert calls.count("/view") == 1, "retry sent the artifact request twice"
        assert unrelated.read() == b"x"
        assert not client.is_closed
        assert client.get("/history/job").status_code == 200
        assert not any(isinstance(t, threading.Timer) for t in threading.enumerate())


def test_successful_stream_cancels_deadline_timer(tmp_path):
    source = tmp_path / "input.png"
    source.write_bytes(b"fixture")
    with (
        artifact_server("continuous") as (url, _disconnected, _calls),
        httpx.Client(base_url=url, timeout=5, trust_env=False) as client,
    ):
        paths = native_backend.generate(
            client, source, tmp_path / "out", validate=False, timeout=3
        )
        assert len(paths) == 1
        assert (
            paths[0].read_bytes() == struct.pack("<4sII", b"glTF", 2, 76) + b"xx" * 32
        )
        assert not any(isinstance(t, threading.Timer) for t in threading.enumerate())
