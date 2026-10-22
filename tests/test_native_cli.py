"""Installed CLI → owned child → HTTP workflow fixture (not inference)."""

import subprocess
import sys
from pathlib import Path


def test_installed_native_local_cli_executes_backend(tmp_path):
    checkout = tmp_path / "ComfyUI"
    checkout.mkdir()
    (checkout / "main.py").write_text("""
import json,sys,struct
from http.server import HTTPServer,BaseHTTPRequestHandler
from comfy_prompt_cli.native_backend import build_prompt
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def reply(self, data):
        self.send_response(200);self.end_headers();self.wfile.write(json.dumps(data).encode())
    def do_GET(self):
        if self.path == '/system_stats': return self.reply({'system':{'argv':sys.argv}})
        if self.path == '/object_info':
            info={}
            for node in build_prompt('source.png').values():
                info[node['class_type']]={'input':{'required':{k:['*'] for k in node['inputs']}},'output':['*']*3}
            return self.reply(info)
        if self.path.startswith('/history/'):
            return self.reply({'job':{'status':{'completed':True},'outputs':{'save':{'3d':[{'filename':'fixture.glb','subfolder':'','type':'output'}]}}}})
        if self.path.startswith('/view?'):
            self.send_response(200);self.end_headers();self.wfile.write(struct.pack('<4sII',b'glTF',2,24)+b'fixture-data');return
        self.send_error(404)
    def do_POST(self):
        body=self.rfile.read(int(self.headers['Content-Length']))
        if self.path == '/upload/image': return self.reply({'name':'uploaded.png','subfolder':'','type':'input'})
        if self.path == '/prompt':
            data=json.loads(body)
            assert data['prompt']['image']['inputs']['image']=='uploaded.png'
            assert data['prompt']['shape_sample']['inputs']['seed']==123
            assert data['prompt']['save']['class_type']=='SaveGLB'
            return self.reply({'prompt_id':'job','node_errors':{}})
        self.send_error(404)
HTTPServer(('127.0.0.1',int(sys.argv[sys.argv.index('--port')+1])),Handler).serve_forever()
""")
    image = tmp_path / "source.png"
    image.write_bytes(b"fixture")
    cli = Path(sys.executable).parent / "comfy-prompt-cli"
    if not cli.exists():
        # uv --with pytest uses a tool env but the project itself is installed.
        cli = Path(__file__).parents[1] / ".venv/bin/comfy-prompt-cli"
    result = subprocess.run(
        [
            str(cli),
            "image-to-glb",
            "--backend",
            "native-local",
            "--image",
            str(image),
            "--native-python",
            sys.executable,
            "--native-checkout",
            str(checkout),
            "--native-runs",
            str(tmp_path / "runs"),
            "--native-device",
            "cpu",
            "--mesh-seed",
            "123",
            "--out-dir",
            str(tmp_path / "out"),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Downloaded" in result.stdout
    assert len(list((tmp_path / "out").glob("*.glb"))) == 1
