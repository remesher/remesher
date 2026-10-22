"""Real isolated CLI subprocess + local HTTP ComfyUI fixture, never GPU evidence.

Run with REMESHER_TEST_CLI=/absolute/venv/bin/comfy-prompt-cli.
"""

import base64
import json
import os
import struct
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from test_plugin import load_plugin


@unittest.skipUnless(
    os.environ.get("REMESHER_TEST_CLI"),
    "Set REMESHER_TEST_CLI to exercise the actual CLI",
)
class ActualCLIContract(unittest.TestCase):
    def test_health_upload_prompt_history_download(self):
        requests = []
        glb_json = b'{"asset":{"version":"2.0"}}  '
        glb = (
            struct.pack("<4sII", b"glTF", 2, 20 + len(glb_json))
            + struct.pack("<I4s", len(glb_json), b"JSON")
            + glb_json
        )

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def respond(self, value, status=200):
                body = value if isinstance(value, bytes) else json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                requests.append(("GET", self.path))
                if self.path == "/system_stats":
                    self.respond({"system": {"fixture": True}})
                elif self.path == "/queue":
                    self.respond({"queue_running": [], "queue_pending": []})
                elif self.path == "/history/fixture-prompt":
                    self.respond(
                        {
                            "fixture-prompt": {
                                "outputs": {"2": {"mesh": ["fixture.glb"]}},
                                "status": {"status_str": "success", "completed": True},
                            }
                        }
                    )
                elif self.path.startswith("/view"):
                    self.respond(glb)
                else:
                    self.respond({}, 404)

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                requests.append(("POST", self.path))
                if self.path == "/upload/image":
                    assert b"image" in body
                    self.respond(
                        {"name": "fixture.png", "subfolder": "", "type": "input"}
                    )
                elif self.path == "/prompt":
                    prompt = json.loads(body)["prompt"]
                    assert any(
                        node.get("class_type") == "LoadImage"
                        and node["inputs"]["image"] == "fixture.png"
                        for node in prompt.values()
                    )
                    self.respond({"prompt_id": "fixture-prompt"})
                else:
                    self.respond({}, 404)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "config.json"
            config.write_text(
                json.dumps({"server_url": f"http://127.0.0.1:{server.server_port}/"})
            )
            workflow = root / "workflow.json"
            workflow.write_text(
                (
                    Path(__file__).resolve().parents[3]
                    / "examples"
                    / "img_to_trellis2.json"
                ).read_text()
            )
            image = root / "test.png"
            image.write_bytes(
                base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a2ioAAAAASUVORK5CYII="
                )
            )
            plugin = load_plugin()
            plugin.data_root = lambda: root / "state"
            with patch.dict(
                os.environ,
                {
                    "REMESHER_CLI": os.environ["REMESHER_TEST_CLI"],
                    "REMESHER_CONFIG": str(config),
                    "REMESHER_WORKFLOW": str(workflow),
                    "PYTHONPATH": "/does-not-exist",
                    "UV_PROJECT_ENVIRONMENT": "/does-not-exist",
                },
            ):
                self.assertEqual(plugin.health({})["status"], "healthy")
                result = plugin.generate({"image": str(image), "timeout_seconds": 10})
                self.assertEqual(result["status"], "queued", result)
                final = result
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    final = plugin.job({"job_id": result["job_id"]})
                    if final["status"] not in ("queued", "running"):
                        break
                    time.sleep(0.05)
                self.assertEqual(
                    final["status"], "succeeded", Path(final["log_path"]).read_text()
                )
                self.assertEqual(Path(final["assets"][0]["path"]).read_bytes(), glb)
            for request in (
                ("GET", "/system_stats"),
                ("POST", "/upload/image"),
                ("POST", "/prompt"),
                ("GET", "/history/fixture-prompt"),
            ):
                self.assertIn(request, requests)
