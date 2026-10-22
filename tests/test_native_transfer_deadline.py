"""Real HTTP streaming deadline regressions, with a bounded loopback peer."""

import json
import struct
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import httpx
import pytest

from comfy_prompt_cli import native_backend


@contextmanager
def artifact_server(mode):
    stopped = threading.Event()
    disconnected = threading.Event()
    calls = []

    class Handler(BaseHTTPRequestHandler):
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
            self.send_response(200)
            self.send_header("Content-Length", "76")
            self.end_headers()
            try:
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


@pytest.mark.parametrize("mode", ["continuous", "late-stall"])
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
