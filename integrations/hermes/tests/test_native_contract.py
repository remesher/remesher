"""Real native CLI + disposable HTTP child; NOT inference or model validation."""

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from test_plugin import load_plugin

# Deliberately permissive fixture schema: validates transport/argv, not node schemas.
SERVER = """
import json, os, sys, struct
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from comfy_prompt_cli.native_backend import build_prompt
Path(__file__).with_name('pid').write_text(str(os.getpid()))
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def reply(self, data):
        body = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.send_response(200); self.send_header('Content-Length', str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path == '/system_stats': return self.reply({'system': {'argv': sys.argv}})
        if self.path == '/object_info':
            info = {}
            for node in build_prompt('source.png').values():
                info[node['class_type']] = {'input': {'required': {k: ['*'] for k in node['inputs']}}, 'output': ['*'] * 3}
            return self.reply(info)
        if self.path.startswith('/history/'):
            if Path(__file__).with_name('stall').exists(): return self.reply({})
            return self.reply({'job': {'status': {'completed': True}, 'outputs': {'save': {'3d': [{'filename': 'fixture.glb', 'subfolder': '', 'type': 'output'}]}}}})
        if self.path.startswith('/view?'): return self.reply(struct.pack('<4sII', b'glTF', 2, 24) + b'fixture-data')
        self.send_error(404)
    def do_POST(self):
        body = self.rfile.read(int(self.headers['Content-Length']))
        if self.path == '/upload/image': return self.reply({'name': 'uploaded.png', 'subfolder': '', 'type': 'input'})
        if self.path == '/prompt':
            prompt = json.loads(body)['prompt']
            assert prompt['image']['inputs']['image'] == 'uploaded.png'
            assert prompt['save']['class_type'] == 'SaveGLB'
            Path(__file__).with_name('submitted').touch()
            return self.reply({'prompt_id': 'job', 'node_errors': {}})
        self.send_error(404)
server = HTTPServer(('127.0.0.1', int(sys.argv[sys.argv.index('--port') + 1])), Handler)
Path(__file__).with_name('port').write_text(str(server.server_port))
server.serve_forever()
"""


@unittest.skipUnless(
    os.environ.get("REMESHER_TEST_NATIVE_CLI"),
    "Set REMESHER_TEST_NATIVE_CLI to exercise native CLI",
)
class NativeCLIContract(unittest.TestCase):
    def exercise(self, backend, stall=False):
        cli = os.environ["REMESHER_TEST_NATIVE_CLI"]
        python = os.environ.get(
            "REMESHER_TEST_NATIVE_PYTHON", str(Path(cli).parent / "python")
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkout = root / "Comfy UI"
            checkout.mkdir()
            (checkout / "main.py").write_text(SERVER)
            if stall:
                (checkout / "stall").touch()
            cfg = {
                "cli": cli,
                "backend": backend,
                "native_python": python,
                "native_checkout": str(checkout),
                "native_device": "cpu",
            }
            server = None
            try:
                if backend == "native":
                    server = subprocess.Popen(
                        [python, str(checkout / "main.py"), "--port", "0"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    end = time.monotonic() + 10
                    while not (checkout / "port").exists() and time.monotonic() < end:
                        time.sleep(0.05)
                    cfg["native_server"] = (
                        "http://127.0.0.1:" + (checkout / "port").read_text()
                    )
                settings = root / "settings.json"
                settings.write_text(json.dumps(cfg))
                image = root / "image.png"
                image.write_bytes(b"fixture")
                plugin = load_plugin()
                plugin.data_root = lambda: root / "state"
                with patch.dict(os.environ, {"REMESHER_SETTINGS": str(settings)}):
                    health = plugin.health({})
                    self.assertEqual(
                        health["status"],
                        "healthy" if backend == "native" else "configured",
                    )
                    self.assertFalse(health["gpu_generation_verified"])
                    result = plugin.generate(
                        {"image": str(image), "timeout_seconds": 3 if stall else 15}
                    )
                self.assertEqual(result["status"], "queued", result)
                end = time.monotonic() + 25
                while time.monotonic() < end:
                    result = plugin.job({"job_id": result["job_id"]})
                    if result["status"] not in ("queued", "running"):
                        break
                    time.sleep(0.05)
                self.assertEqual(
                    result["status"],
                    "timed_out" if stall else "succeeded",
                    Path(result["log_path"]).read_text(),
                )
                self.assertTrue((checkout / "submitted").exists())
                if not stall:
                    self.assertEqual(
                        len(plugin.assets({"job_id": result["job_id"]})["assets"]), 1
                    )
                if backend == "native-local":
                    pid = int((checkout / "pid").read_text())
                    with self.assertRaises(ProcessLookupError):
                        os.kill(pid, 0)
                else:
                    assert server is not None
                    self.assertIsNone(
                        server.poll(), "Plugin killed an operator-managed server"
                    )
            finally:
                if server is not None:
                    server.terminate()
                    server.wait(timeout=5)

    def test_native_existing_server(self):
        self.exercise("native")

    def test_native_local_owned_server(self):
        self.exercise("native-local")

    def test_native_local_deadline_reaps_owned_server(self):
        self.exercise("native-local", stall=True)
