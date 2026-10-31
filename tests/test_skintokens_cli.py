import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import comfy_prompt_cli as cli

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("beams", [None, 1, 20])
def test_skintokens_rig_dispatch(tmp_path, monkeypatch, beams):
    captured = {}
    mesh = tmp_path / "robot.glb"
    mesh.write_bytes(b"input fixture")
    output = tmp_path / "rigged.glb"
    monkeypatch.setattr(cli, "_load_config", lambda _: SimpleNamespace(server_url="http://example.invalid"))
    monkeypatch.setattr(cli, "_upload_input_asset", lambda *a, **kw: "uploads/robot.glb")
    def submit(**kwargs):
        captured.update(kwargs)
        return [output]
    monkeypatch.setattr(cli, "_submit_wait_and_download", submit)
    monkeypatch.setattr(cli, "_postprocess_rig_downloads", lambda *a, **kw: pytest.fail("MIA autoskin must not run"))
    args = ["rig-glb", "--rigging-backend", "skintokens", "--mesh", str(mesh)]
    if beams is not None:
        args += ["--num-beams", str(beams)]
    result = CliRunner().invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    node = next(iter(captured["prompt"].values()))
    assert node["class_type"] == "SkinTokensRigGLB"
    assert node["inputs"] == {"glb_path": "uploads/robot.glb", "output_name": "robot.glb", "use_skeleton": False, "use_transfer": True, "use_postprocess": False, "num_beams": 10 if beams is None else beams}
    assert str(output) in result.output
    assert captured["extensions"] == {".glb"}


@pytest.fixture
def wide_plain_cli(monkeypatch):
    # TERM=dumb makes Rich force an 80-column layout even with COLUMNS set,
    # truncating flags and wrapping error messages. Use a fixed-width, unstyled
    # renderer for literal content assertions, without changing CLI behavior.
    import typer.rich_utils

    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.setattr(typer.rich_utils, "MAX_WIDTH", 160)
    monkeypatch.setattr(typer.rich_utils, "COLOR_SYSTEM", None)
    return CliRunner()


@pytest.mark.parametrize("command,args", [("rig-glb", []), ("text-to-rigged-glb", ["--prompt", "robot"])])
def test_backend_help_and_invalid_value(command, args, wide_plain_cli):
    runner = wide_plain_cli
    help_result = runner.invoke(cli.app, [command, "--help"])
    assert help_result.exit_code == 0
    assert "--rigging-backend" in help_result.output
    assert "--rig-seed" not in help_result.output
    result = runner.invoke(cli.app, [command, *args, "--rigging-backend", "typo"])
    assert result.exit_code == 2
    assert "must be one of: mia, skintokens" in result.output


def test_skintokens_end_to_end(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "_load_config", lambda _: SimpleNamespace(server_url="http://example.invalid"))
    def submit(**kwargs):
        calls.append(kwargs)
        return [tmp_path / ("image.png" if kwargs["extensions"] == cli.IMAGE_EXTENSIONS else "rigged.glb")]
    monkeypatch.setattr(cli, "_submit_wait_and_download", submit)
    monkeypatch.setattr(cli, "_upload_input_image", lambda *a: "image.png")
    monkeypatch.setattr(cli, "_submit_prompt", lambda *a: {"prompt_id": "p"})
    async def wait(*a, **kw):
        return {}, {"outputs": {"1": {"files": [{"filename": "generated.glb"}]}}}
    monkeypatch.setattr(cli, "_wait_for_completion", wait)
    monkeypatch.setattr(cli, "_download_from_history_by_ext", lambda *a: [tmp_path / "generated.glb"])
    monkeypatch.setattr(cli, "_upload_input_asset", lambda *a, **kw: "uploaded/generated.glb")
    monkeypatch.setattr(cli, "_postprocess_rig_downloads", lambda *a, **kw: pytest.fail("MIA postprocessing"))
    result = CliRunner().invoke(cli.app, ["text-to-rigged-glb", "--prompt", "robot", "--rigging-backend", "skintokens", "--use-skeleton", "--no-use-transfer", "--use-postprocess", "--seed", "42", "--num-beams", "3", "--glb-name", "custom"])
    assert result.exit_code == 0, result.output
    assert len(calls) == 2
    image_sampler = cli._find_node_by_class(calls[0]["prompt"], "KSampler")
    assert image_sampler is not None
    assert image_sampler[1]["inputs"]["seed"] == 42
    assert calls[-1]["out_dir"].name == "text_to_rigged_glb_rigged"
    assert calls[-1]["prompt"]["1"]["inputs"] == {"glb_path": "uploaded/generated.glb", "output_name": "custom.glb", "use_skeleton": True, "use_transfer": False, "use_postprocess": True, "num_beams": 3}


def test_retarget_worker_rejects_generic_bones():
    import runpy
    worker = runpy.run_path(str(ROOT / "docker/demo-jupyter/scripts/arp_retarget_worker.py"))
    validate = worker["_validate_target_bones"]
    with pytest.raises(ValueError, match="SkinTokens.*unsupported"):
        validate({"bone_0", "bone_1"})
    validate({"mixamorig:Hips", "mixamorig:Spine"})


@pytest.mark.parametrize("name,expected", [("rig", "rig.glb"), ("nested/rig.glb", "nested/rig.glb"), ("rig.GLB", "rig.GLB")])
def test_output_names(name, expected):
    assert cli._skintokens_output_name(name) == expected


@pytest.mark.parametrize("name", ["", " ", "../escape", "/absolute.glb", "C:\\rig.glb"])
def test_unsafe_output_names(name):
    import typer
    with pytest.raises(typer.BadParameter, match="output name"):
        cli._skintokens_output_name(name)


@pytest.mark.parametrize("args,message", [
    (["--num-beams", "0"], "Invalid value"),
    (["--num-beams", "21"], "Invalid value"),
    (["--rig-seed", "0"], "No such option"),
])
@pytest.mark.parametrize("command", ["rig-glb", "text-to-rigged-glb"])
def test_invalid_parameters_fail_before_submission(args, message, command):
    result = CliRunner().invoke(cli.app, [command, "--rigging-backend", "skintokens", *args])
    assert result.exit_code == 2
    assert message in result.output
    assert args[0] in result.output


@pytest.mark.parametrize("workflow,mesh,message", [
    ({"1": {"class_type": "MIAAutoRig", "inputs": {}}}, "robot.glb", "requires a SkinTokensRigGLB node"),
    ({"1": {"class_type": "SkinTokensRigGLB", "inputs": {}}}, None, "requires --mesh"),
    ({"1": {"class_type": "SkinTokensRigGLB", "inputs": None}}, "robot.glb", "inputs must be an object"),
    ({"1": {"class_type": "SkinTokensRigGLB", "inputs": {"seed": 0}}}, "robot.glb", "does not support seed"),
])
def test_invalid_workflows(tmp_path, monkeypatch, workflow, mesh, message):
    path = tmp_path / "workflow.json"
    path.write_text(json.dumps(workflow))
    monkeypatch.setattr(cli, "_load_config", lambda _: SimpleNamespace(server_url="http://example.invalid"))
    args = ["rig-glb", "--rigging-backend", "skintokens", "--workflow-file", str(path)]
    if mesh:
        args += ["--mesh", mesh]
    result = CliRunner().invoke(cli.app, args)
    assert result.exit_code == 2, result.output
    assert message in result.output


def test_example_matches_generated_workflow():
    example = json.loads((ROOT / "examples/rig_glb_skintokens.json").read_text())
    generated = cli._skintokens_prompt(None, "input.glb", None, use_skeleton=False, use_transfer=True, use_postprocess=False, num_beams=10)
    assert example["1"]["inputs"] == generated["1"]["inputs"]
    assert example["1"]["class_type"] == generated["1"]["class_type"]


@pytest.mark.parametrize("output_mode", ["files", "missing", "error"])
def test_skintokens_http_download_contract(tmp_path, output_mode, wide_plain_cli):
    """Exercise the real CLI HTTP path against a local protocol fixture, not inference."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlparse, parse_qs

    received = []
    artifact = b"explicit protocol fixture; not a generated GLB"
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass
        def send(self, body):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send(b'{"prompt_id":"fixture"}')
        def do_GET(self):
            path = urlparse(self.path)
            if path.path == "/queue":
                self.send(b'{"queue_running":[],"queue_pending":[]}')
            elif path.path == "/history/fixture":
                history = {"status": {"completed": True}, "outputs": {}}
                if output_mode == "files":
                    history["outputs"] = {"1": {"files": [{"filename": "robot.glb", "subfolder": "skintokens", "type": "output"}]}}
                elif output_mode == "error":
                    history["status"] = {"status_str": "error", "messages": [["execution_error", {"node_type": "SkinTokensRigGLB", "exception_message": "fixture inference failure"}]]}
                self.send(json.dumps({"fixture": history}).encode())
            elif path.path == "/view":
                assert parse_qs(path.query) == {"filename": ["robot.glb"], "subfolder": ["skintokens"], "type": ["output"]}
                self.send(artifact)
            else:
                self.send_error(404)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"server_url": f"http://127.0.0.1:{server.server_port}"}))
    try:
        result = wide_plain_cli.invoke(cli.app, ["rig-glb", "--rigging-backend", "skintokens", "--workflow-file", str(ROOT / "examples/rig_glb_skintokens.json"), "--mesh", "remote/robot.glb", "--config", str(config), "--out-dir", str(tmp_path), "--timeout", "3", "--poll-interval", "0.5"])
        if output_mode != "files":
            assert result.exit_code == 2, result.output
            assert ("fixture inference failure" if output_mode == "error" else ".glb") in result.output
            assert "Downloaded" not in result.output
            assert not list(tmp_path.rglob("*.glb"))
            return
        assert result.exit_code == 0, result.output
        assert received[0]["prompt"]["1"]["inputs"]["glb_path"] == "remote/robot.glb"
        files = list(tmp_path.rglob("*.glb"))
        assert len(files) == 1
        assert files[0].read_bytes() == artifact
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
