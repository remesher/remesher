"""macOS adapter policy; fixture transport is not model inference."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from test_plugin import load_plugin


def config(tmp_path):
    checkout = tmp_path / "Comfy UI"
    checkout.mkdir()
    (checkout / "main.py").touch()
    models = tmp_path / "external models"
    models.mkdir()
    python = tmp_path / "venv-python"
    python.symlink_to(sys.executable)
    return dict(
        cli=sys.executable,
        backend="native-local",
        native_python=str(python),
        native_checkout=str(checkout),
        native_device="mps",
        native_models=str(models),
    )


def test_directory_alias_snapshot_regression(tmp_path):
    # Reproduce /var versus /private/var on any POSIX filesystem, without
    # changing TMPDIR globally or resolving the configured interpreter.
    from test_plugin import PluginTests

    actual = tmp_path / "actual"
    actual.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    case = PluginTests(
        "test_native_config_uses_private_snapshot_without_conflicting_flags"
    )
    case.root = alias
    try:
        case.test_native_config_uses_private_snapshot_without_conflicting_flags()
    finally:
        case.doCleanups()


def test_explicit_mps_environment_is_validated_and_never_ambient(tmp_path):
    plugin = load_plugin()
    raw = config(tmp_path)
    env = {"PYTORCH_ENABLE_MPS_FALLBACK": "1", "OMP_NUM_THREADS": "4"}
    cfg = plugin.validate_settings({**raw, "environment": env})
    with patch.dict(os.environ, env):
        assert not (plugin.cli_environment().keys() & env.keys())
        assert plugin.cli_environment(cfg).items() >= env.items()
    for key, value in [
        ("PYTORCH_ENABLE_MPS_FALLBACK", "yes"),
        ("OMP_NUM_THREADS", "0"),
        ("OMP_NUM_THREADS", "999"),
    ]:
        with pytest.raises(ValueError):
            plugin.validate_settings({**raw, "environment": {key: value}})


def test_mps_settings_keep_interpreter_and_models(tmp_path):
    plugin = load_plugin()
    cfg = plugin.validate_settings(config(tmp_path))
    argv = plugin.backend_arguments(cfg, tmp_path)
    assert argv[argv.index("--native-python") + 1] == cfg["native_python"]
    assert argv[argv.index("--native-models") + 1] == cfg["native_models"]
    assert argv[argv.index("--native-device") + 1] == "mps"


@pytest.mark.parametrize("value", [True, 0, 43201, float("inf"), "43200"])
def test_long_job_cap_rejects_invalid_settings(tmp_path, value):
    plugin = load_plugin()
    cfg = config(tmp_path)
    cfg.update(native_device="cpu", max_timeout_seconds=value)
    with pytest.raises(ValueError, match="max_timeout_seconds"):
        plugin.validate_settings(cfg)


def test_long_job_requires_operator_and_request_opt_in(tmp_path):
    plugin = load_plugin()
    cfg = config(tmp_path)
    cfg["native_device"] = "cpu"
    image = tmp_path / "image.png"
    image.write_bytes(b"fixture")
    plugin.data_root = lambda: tmp_path / "state"
    with patch.object(plugin, "settings", return_value=plugin.validate_settings(cfg)):
        assert (
            plugin.generate(dict(image=str(image), timeout_seconds=43200))["status"]
            == "invalid_request"
        )
    cfg = plugin.validate_settings({**cfg, "max_timeout_seconds": 43200})
    with (
        patch.object(plugin, "settings", return_value=cfg),
        patch.object(plugin.subprocess, "Popen"),
    ):
        result = plugin.generate(dict(image=str(image), timeout_seconds=43200))
    assert result["status"] == "queued", result
    folder = Path(result["log_path"]).parent
    argv = json.loads((folder / "request.json").read_text())["argv"]
    assert argv[argv.index("--timeout") + 1] == "43200"
    assert 43199 < result["deadline"] - result["created_at"] < 43201


def test_timeout_cap_environment_is_integer(tmp_path):
    plugin = load_plugin()
    cfg = config(tmp_path)
    with patch.dict(
        os.environ,
        {
            **{"REMESHER_" + k.upper(): v for k, v in cfg.items()},
            "REMESHER_MAX_TIMEOUT_SECONDS": "43200",
        },
        clear=True,
    ):
        assert plugin.settings()["max_timeout_seconds"] == 43200


def test_final_reap_is_bounded_and_records_pending_cleanup(tmp_path):
    import subprocess
    import time
    from unittest.mock import MagicMock

    plugin = load_plugin()
    process = MagicMock()
    process.wait.side_effect = subprocess.TimeoutExpired("fixture", 5)
    selector = MagicMock()
    selector.__enter__.return_value = selector
    selector.get_map.return_value = {}
    with (
        patch.object(plugin.subprocess, "Popen", return_value=process),
        patch.object(plugin.selectors, "DefaultSelector", return_value=selector),
        patch.object(plugin.os, "killpg"),
    ):
        with pytest.raises(plugin.CleanupPendingError):
            plugin.run_cli(["fixture"], tmp_path, 1, {})
    assert all(
        call.kwargs.get("timeout") is not None for call in process.wait.call_args_list
    )
    process.stdout.close.assert_called_once()
    folder = tmp_path / "jobs" / ("a" * 32)
    folder.mkdir(parents=True)
    (folder / "request.json").write_text(json.dumps({"argv": ["fixture"], "env": {}}))
    state = dict(status="queued", deadline=time.time() + 20)
    with patch.object(
        plugin, "run_cli", side_effect=plugin.CleanupPendingError("cleanup pending")
    ):
        plugin._worker_locked(folder, state)
    saved = plugin.read_state(folder)
    assert saved["status"] == "failed" and saved["cleanup_pending"]
    plugin.data_root = lambda: tmp_path
    assert plugin.generate({})["status"] == "busy"


@pytest.mark.parametrize("timeout", [True, 0, -1, float("nan"), float("inf"), 43201])
def test_native_backend_rejects_unbounded_timeout_before_network(tmp_path, timeout):
    from comfy_prompt_cli.native_backend import generate

    with pytest.raises(ValueError, match="timeout"):
        generate(None, tmp_path / "absent.png", tmp_path, timeout=timeout)


def test_darwin_installer_rejects_unsupported_python_before_mutation(tmp_path, monkeypatch):
    from comfy_prompt_cli import native_setup

    monkeypatch.setattr(native_setup.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(native_setup.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(native_setup.platform, "python_version", lambda: "3.14.3")
    with pytest.raises(ValueError, match="3.12.12"):
        native_setup.install(native_setup.SetupConfig.at_root(tmp_path / "runtime"))
    assert not (tmp_path / "runtime").exists()


def test_mps_native_config_preserves_environment_policy(tmp_path):
    from comfy_prompt_cli.native_setup import SetupConfig

    plugin = load_plugin()
    config = SetupConfig.at_root(tmp_path / "internal").model_copy(
        update={"device": "mps", "mps_fallback": False, "omp_num_threads": 3}
    )
    path = tmp_path / "native.json"
    path.write_text(config.model_dump_json())
    cfg = plugin.validate_settings({"cli": sys.executable, "backend": "native-local", "native_config": str(path)})
    folder = tmp_path / "job"
    folder.mkdir()
    argv = plugin.backend_arguments(cfg, folder)
    snapshot = json.loads(Path(argv[argv.index("--native-config") + 1]).read_text())
    assert snapshot["device"] == "mps"
    assert snapshot["mps_fallback"] is False
    assert snapshot["omp_num_threads"] == 3
    for field, value in [("mps_fallback", "yes"), ("omp_num_threads", True), ("omp_num_threads", 0)]:
        path.write_text(json.dumps({**config.model_dump(mode="json"), field: value}))
        with pytest.raises(ValueError):
            plugin.read_native_config(path)


def test_native_models_rejects_config_mode(tmp_path):
    plugin = load_plugin()
    cfg = config(tmp_path)
    native = tmp_path / "native.json"
    native.write_text("{}")
    with pytest.raises(ValueError):
        plugin.validate_settings(
            dict(
                cli=sys.executable,
                backend="native-local",
                native_config=str(native),
                native_models=cfg["native_models"],
            )
        )
