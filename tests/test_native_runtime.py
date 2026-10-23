"""Real disposable child processes, not GPU inference tests."""

import socket
import sys
from pathlib import Path

import pytest

from comfy_prompt_cli import native_runtime


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "comfy"
    root.mkdir()
    (root / "main.py").write_text("""
import sys,json
from http.server import HTTPServer,BaseHTTPRequestHandler
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body=json.dumps({"system":{"argv":sys.argv}}).encode()
        self.send_response(200);self.end_headers();self.wfile.write(body)
    def log_message(self,*args): pass
port=int(sys.argv[sys.argv.index('--port')+1])
HTTPServer(('127.0.0.1',port),Handler).serve_forever()
""")
    return root


def test_mps_uses_autodetection_and_checks_reported_device(checkout, tmp_path):
    source = (checkout / "main.py").read_text()
    (checkout / "main.py").write_text(source.replace(
        '"system":{"argv":sys.argv}', '"system":{"argv":sys.argv},"devices":[{"type":"mps"}]'))
    with native_runtime.LocalRuntime(
        Path(sys.executable), checkout, tmp_path / "runs", device="mps"
    ) as runtime:
        assert "--cpu" not in runtime.argv
        assert "--cuda-device" not in runtime.argv
        assert "--mps" not in runtime.argv  # pinned ComfyUI has no such flag
    assert runtime.process.poll() is not None


def test_mps_rejects_silent_cpu_fallback_and_cleans_up(checkout, tmp_path):
    runtime = native_runtime.LocalRuntime(
        Path(sys.executable), checkout, tmp_path / "runs", device="mps", startup_timeout=2
    )
    with pytest.raises(RuntimeError, match="MPS"), runtime:
        pytest.fail("accepted absent MPS device")
    assert runtime.process.poll() is not None


def test_owned_child_ready_and_reaped(checkout, tmp_path):
    with native_runtime.LocalRuntime(
        Path(sys.executable), checkout, tmp_path / "runs", device="cpu"
    ) as runtime:
        process = runtime.process
        assert process.poll() is None
        assert runtime.base_url.startswith("http://127.0.0.1:")
        assert "--disable-all-custom-nodes" in runtime.argv
        assert "--cpu" in runtime.argv
        assert runtime.run_dir.stat().st_mode & 0o077 == 0
    assert process.poll() is not None


def test_configured_model_path_is_visible_to_child(checkout, tmp_path):
    import json

    models = tmp_path / "models with spaces"
    models.mkdir()
    (models / "vae").mkdir()
    (models / "vae" / "fixture.safetensors").write_bytes(b"fixture")
    code = (checkout / "main.py").read_text()
    (checkout / "main.py").write_text(
        "import json, pathlib, sys\nsettings=json.loads(pathlib.Path(sys.argv[sys.argv.index('--extra-model-paths-config')+1]).read_text())\nassert (pathlib.Path(settings['remesher']['base_path'])/'vae'/'fixture.safetensors').read_bytes()==b'fixture'\n"
        + code
    )
    with native_runtime.LocalRuntime(
        Path(sys.executable), checkout, tmp_path / "runs", models=models, device="cpu"
    ) as runtime:
        settings = json.loads((runtime.run_dir / "models.yaml").read_text())
        assert settings["remesher"]["base_path"] == str(models)
        assert settings["remesher"]["is_default"] is True
        assert settings["remesher"]["geometry_estimation"] == "geometry_estimation"
        assert runtime.process.poll() is None


def test_sigterm_restores_handler_and_reaps_owned_child(checkout, tmp_path):
    import os
    import signal

    original = signal.getsignal(signal.SIGTERM)
    runtime = native_runtime.LocalRuntime(
        Path(sys.executable), checkout, tmp_path / "runs"
    )
    # Inspect before delivering so RED cannot kill the pytest process.
    with runtime:
        assert signal.getsignal(signal.SIGTERM) != original
        with pytest.raises(SystemExit):
            os.kill(os.getpid(), signal.SIGTERM)
    assert runtime.process.poll() is not None
    assert signal.getsignal(signal.SIGTERM) == original


def test_wrong_server_identity_is_never_adopted(checkout, tmp_path):
    source = (
        (checkout / "main.py")
        .read_text()
        .replace('"argv":sys.argv', '"argv":["unrelated-server"]')
    )
    (checkout / "main.py").write_text(source)
    runtime = native_runtime.LocalRuntime(
        Path(sys.executable), checkout, tmp_path / "runs", startup_timeout=0.3
    )
    with pytest.raises(RuntimeError, match="identity"), runtime:
        pytest.fail("adopted wrong identity")
    assert runtime.process.poll() is not None


def test_busy_port_is_not_adopted(checkout, tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        with (
            pytest.raises(ValueError, match="port"),
            native_runtime.LocalRuntime(
                Path(sys.executable),
                checkout,
                tmp_path / "runs",
                port=sock.getsockname()[1],
            ),
        ):
            pytest.fail("adopted unrelated listener")
        assert sock.getsockname()[1] > 0


def test_early_exit_and_exception_cleanup(checkout, tmp_path):
    (checkout / "main.py").write_text("raise SystemExit(17)")
    runtime = native_runtime.LocalRuntime(
        Path(sys.executable), checkout, tmp_path / "runs", startup_timeout=2
    )
    with pytest.raises(RuntimeError, match="exited"), runtime:
        pass
    assert runtime.process.poll() == 17


def test_keyboard_interrupt_reaps_child(checkout, tmp_path):
    runtime = native_runtime.LocalRuntime(
        Path(sys.executable), checkout, tmp_path / "runs"
    )
    with pytest.raises(KeyboardInterrupt), runtime:
        raise KeyboardInterrupt()
    assert runtime.process.poll() is not None
