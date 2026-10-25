"""Invocation approval and environment parity; fixtures are not GPU evidence."""

import json
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
from test_plugin import load_plugin


@pytest.fixture
def configured(tmp_path, monkeypatch):
    plugin = load_plugin()
    native = tmp_path / "native.json"
    native.write_text(json.dumps({
        **{key: str(tmp_path / key) for key in ("venv", "checkout", "models", "runs", "output")},
        "device": "mps",
    }))
    raw = {"cli": sys.executable, "backend": "native-local", "native_config": str(native)}
    image = tmp_path / "image.png"
    image.write_bytes(b"fixture")
    monkeypatch.setattr(plugin, "data_root", lambda: tmp_path / "state")
    monkeypatch.setattr(plugin, "settings", lambda: plugin.validate_settings(raw))
    monkeypatch.setattr(plugin.subprocess, "Popen", Mock())
    return plugin, raw, image, native


@pytest.mark.parametrize("extra,expected", [({}, False), ({"native_allow_low_memory": False}, False), ({"native_allow_low_memory": True}, True)])
def test_invocation_approval_argv_and_audit(configured, extra, expected):
    plugin, _raw, image, native = configured
    original = native.read_bytes()
    result = plugin.generate({"image": str(image), **extra})
    assert result["status"] == "queued", result
    folder = Path(result["log_path"]).parent
    request = json.loads((folder / "request.json").read_text())
    assert ("--native-allow-low-memory" in request["argv"]) is expected
    assert request["native_allow_low_memory"] is expected
    assert result["native_allow_low_memory"] is expected
    assert plugin.job({"job_id": result["job_id"]})["native_allow_low_memory"] is expected
    assert "native_allow_low_memory" not in json.loads((folder / "native-setup.json").read_text())
    assert native.read_bytes() == original
    assert request["env"]["PYTORCH_ENABLE_MPS_FALLBACK"] == "1"
    assert request["env"]["OMP_NUM_THREADS"] == "1"


@pytest.mark.parametrize("value", [None, 0, 1, "true", "false", [], {}])
def test_approval_is_strict_boolean_before_spawn(configured, value):
    plugin, _, image, _ = configured
    result = plugin.generate({"image": str(image), "native_allow_low_memory": value})
    assert result["status"] == "invalid_request", result
    assert "native_allow_low_memory" in result["error"]
    plugin.subprocess.Popen.assert_not_called()


@pytest.mark.parametrize("backend", ["comfy3d", "native", "native-local"])
def test_true_requires_native_config_route(configured, monkeypatch, backend):
    plugin, _, image, _ = configured
    monkeypatch.setattr(plugin, "settings", lambda: {"backend": backend})
    result = plugin.generate({"image": str(image), "native_allow_low_memory": True})
    assert result["status"] == "invalid_request", result
    assert "native_config" in result["error"]
    plugin.subprocess.Popen.assert_not_called()


def test_approval_cannot_be_persisted_or_inherited(configured, monkeypatch):
    plugin, raw, image, native = configured
    for value in (True, False):
        with pytest.raises(ValueError):
            plugin.validate_settings({**raw, "native_allow_low_memory": value})
    monkeypatch.setenv("REMESHER_NATIVE_ALLOW_LOW_MEMORY", "true")
    result = plugin.generate({"image": str(image)})
    assert result["native_allow_low_memory"] is False
    data = json.loads(native.read_text())
    native.write_text(json.dumps({**data, "native_allow_low_memory": True}))
    with pytest.raises(ValueError):
        plugin.read_native_config(native)


def test_schema_exposes_default_false_invocation_only():
    plugin = load_plugin()
    ctx = Mock()
    plugin.register(ctx)
    tool = next(c.kwargs for c in ctx.register_tool.call_args_list if c.kwargs["name"] == "remesher_generate")
    prop = tool["schema"]["parameters"]["properties"]["native_allow_low_memory"]
    assert prop["type"] == "boolean" and prop["default"] is False
    assert "native_allow_low_memory" not in plugin.SETTING_KEYS


@pytest.mark.parametrize("typed,environment", [
    ({}, {"PYTORCH_ENABLE_MPS_FALLBACK": "0"}),
    ({}, {"OMP_NUM_THREADS": "4"}),
    ({"mps_fallback": False}, {"PYTORCH_ENABLE_MPS_FALLBACK": "1"}),
    ({"omp_num_threads": 3}, {"OMP_NUM_THREADS": "4"}),
    ({"device": "cpu", "omp_num_threads": 3}, {"OMP_NUM_THREADS": "4"}),
])
def test_conflicting_environment_fails_closed(configured, typed, environment):
    plugin, raw, _, native = configured
    native.write_text(json.dumps({**json.loads(native.read_text()), **typed}))
    with pytest.raises(ValueError, match="conflicts with native_config"):
        plugin.validate_settings({**raw, "environment": environment})


@pytest.mark.parametrize("typed,environment", [
    ({}, {"PYTORCH_ENABLE_MPS_FALLBACK": "1", "OMP_NUM_THREADS": "1"}),
    ({"mps_fallback": False, "omp_num_threads": 3}, {"PYTORCH_ENABLE_MPS_FALLBACK": "0", "OMP_NUM_THREADS": "3"}),
    ({"omp_num_threads": 256}, {}),
    ({"device": "cpu"}, {"OMP_NUM_THREADS": "4"}),
])
def test_effective_environment_matches_native_policy(configured, typed, environment):
    from comfy_prompt_cli.native_setup import load_config

    plugin, raw, _, native = configured
    native.write_text(json.dumps({**json.loads(native.read_text()), **typed}))
    source = {**raw, "environment": environment.copy()}
    cfg = plugin.validate_settings(source)
    assert plugin.validate_settings(cfg) == cfg
    env = plugin.cli_environment(cfg)
    assert env.items() >= load_config(native).runtime_environment.items()
    assert env.items() >= environment.items()
    assert source["environment"] == environment


def test_changed_config_conflict_rechecked_before_snapshot(configured, tmp_path):
    plugin, raw, _, native = configured
    cfg = plugin.validate_settings({**raw, "environment": {"OMP_NUM_THREADS": "1"}})
    native.write_text(json.dumps({**json.loads(native.read_text()), "omp_num_threads": 4}))
    folder = tmp_path / "job"
    folder.mkdir()
    with pytest.raises(ValueError, match="conflicts with native_config"):
        plugin.backend_arguments(cfg, folder)
    assert not (folder / "native-setup.json").exists()


@pytest.mark.parametrize("approved", [False, True])
def test_plugin_argv_reaches_real_cli_memory_gate(configured, monkeypatch, approved):
    """Real Typer CLI parses the plugin command; readiness is a marked fixture."""
    from typer.testing import CliRunner

    from comfy_prompt_cli import app, native_setup

    plugin, _raw, image, _ = configured
    result = plugin.generate({"image": str(image), "native_allow_low_memory": approved})
    assert result["status"] == "queued", result
    request = json.loads((Path(result["log_path"]).parent / "request.json").read_text())
    seen = []

    def fixture_check(config, *, allow_low_memory=False):
        seen.append(allow_low_memory)
        return {"ready": False, "blockers": ["fixture readiness stop (not inference)"]}

    monkeypatch.setattr(native_setup, "check", fixture_check)
    response = CliRunner().invoke(app, request["argv"][1:])
    assert response.exit_code != 0
    assert "fixture readiness stop" in response.output
    assert seen == [approved]


def test_detached_real_cli_config_transport_and_nonsticky_approval(tmp_path, monkeypatch):
    """Real CLI and owned HTTP child; only provisioning readiness is a fixture."""
    from test_native_contract import SERVER

    plugin = load_plugin()
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    # The disposable interpreter symlink is not a provisioned venv. Give this
    # HTTP fixture the test interpreter's import paths, not ambient PYTHONPATH.
    (checkout / "main.py").write_text(
        SERVER.replace("from comfy_prompt_cli.native_backend import build_prompt",
                       f"sys.path[:0] = {sys.path!r}\n"
                       "Path(__file__).with_name('fixture-env.json').write_text(json.dumps({"
                       "key: os.environ.get(key) for key in ('PYTORCH_ENABLE_MPS_FALLBACK', 'OMP_NUM_THREADS')}))\n"
                       "from comfy_prompt_cli.native_backend import build_prompt")
    )
    models = tmp_path / "models"
    models.mkdir()
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").symlink_to(sys.executable)
    native = tmp_path / "native.json"
    native.write_text(json.dumps({
        **{key: str(tmp_path / key) for key in ("venv", "checkout", "models", "runs", "output")},
        "device": "mps", "mps_fallback": False, "omp_num_threads": 3,
    }))
    cli = tmp_path / "fixture-cli"
    cli.write_text(f"#!{sys.executable}\n" + '''
import json, os
from pathlib import Path
from comfy_prompt_cli import main, native_setup
def fixture_check(config, *, allow_low_memory=False):
    Path(config.output).parent.joinpath("fixture-readiness.json").write_text(json.dumps({
        "allow_low_memory": allow_low_memory,
        "fallback": os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK"),
        "threads": os.environ.get("OMP_NUM_THREADS"),
    }))
    return {"ready": allow_low_memory, "blockers": ["fixture memory admission denied"]}
native_setup.check = fixture_check
main()
''')
    cli.chmod(0o700)
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"cli": str(cli), "backend": "native-local", "native_config": str(native)}))
    monkeypatch.setenv("REMESHER_SETTINGS", str(settings))
    monkeypatch.setattr(plugin, "data_root", lambda: tmp_path / "state")
    image = tmp_path / "image.png"
    image.write_bytes(b"fixture")
    original = native.read_bytes()
    for extra, approved in [({"native_allow_low_memory": True}, True), ({}, False)]:
        result = plugin.generate({"image": str(image), "timeout_seconds": 15, **extra})
        assert result["status"] == "queued", result
        end = time.monotonic() + 25
        while time.monotonic() < end:
            result = plugin.job({"job_id": result["job_id"]})
            if result["status"] not in ("queued", "running"):
                break
            time.sleep(0.05)
        assert result["status"] == ("succeeded" if approved else "failed"), Path(result["log_path"]).read_text()
        assert result["native_allow_low_memory"] is approved
        folder = Path(result["log_path"]).parent
        assert json.loads((folder / "fixture-readiness.json").read_text()) == {
            "allow_low_memory": approved, "fallback": "0", "threads": "3",
        }
        request = json.loads((folder / "request.json").read_text())
        assert request["native_allow_low_memory"] is approved
        assert request["env"]["OMP_NUM_THREADS"] == "3"
        if approved:
            assert json.loads((checkout / "fixture-env.json").read_text()) == {
                "PYTORCH_ENABLE_MPS_FALLBACK": "0", "OMP_NUM_THREADS": "3",
            }
            assert len(plugin.assets({"job_id": result["job_id"]})["assets"]) == 1
            import os
            with pytest.raises(ProcessLookupError):
                os.kill(int((checkout / "pid").read_text()), 0)
    assert native.read_bytes() == original
