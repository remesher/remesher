import importlib.util
import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from comfy_prompt_cli import app
from comfy_prompt_cli.native_setup import SetupConfig


def plugin():
    path = Path(__file__).parents[1] / "integrations/hermes/__init__.py"
    spec = importlib.util.spec_from_file_location("pixal_test_plugin", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pixal_plugin_snapshot_selects_config_model(tmp_path):
    p = plugin()
    config = SetupConfig.at_root(tmp_path / "runtime").model_copy(
        update={"model": "pixal3d"}
    )
    file = tmp_path / "setup.json"
    file.write_text(config.model_dump_json())
    cfg = p.validate_settings(
        {"cli": sys.executable, "backend": "native-local", "native_config": str(file)}
    )
    assert cfg["native_model"] == "pixal3d"
    job = tmp_path / "job"
    job.mkdir()
    argv = p.backend_arguments(cfg, job)
    assert argv[argv.index("--native-model") + 1] == "pixal3d"
    snapshot = json.loads((job / "native-setup.json").read_text())
    assert snapshot["model"] == "pixal3d"
    assert snapshot["output"] == str(job / "output")
    assert file.read_text() == config.model_dump_json()
    with pytest.raises(ValueError, match="model"):
        p.validate_settings(
            {
                "cli": sys.executable,
                "backend": "native-local",
                "native_config": str(file),
                "native_model": "trellis2",
            }
        )


def test_pixal_cli_config_reaches_readiness_not_trellis_rejection(
    tmp_path, monkeypatch
):
    import comfy_prompt_cli.native_setup as setup

    config = SetupConfig.at_root(tmp_path / "runtime").model_copy(
        update={"model": "pixal3d"}
    )
    file = tmp_path / "setup.json"
    file.write_text(config.model_dump_json())
    image = tmp_path / "image.png"
    image.write_bytes(b"fixture")
    seen = []

    def check(value, **kw):
        seen.append(value.model)
        return {"ready": False, "blockers": ["readiness sentinel"]}

    monkeypatch.setattr(setup, "check", check)
    result = CliRunner().invoke(
        app,
        [
            "image-to-glb",
            "--image",
            str(image),
            "--backend",
            "native-local",
            "--native-config",
            str(file),
            "--native-model",
            "pixal3d",
        ],
    )
    assert "readiness sentinel" in result.output, result.output
    assert seen == ["pixal3d"]
