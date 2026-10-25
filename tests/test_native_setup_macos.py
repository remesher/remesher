"""macOS provisioning contracts; no network installs or shared runtime mutation."""

import json
import subprocess

import pytest

from comfy_prompt_cli import native_setup as setup


def mac(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(setup.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(setup.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(
        setup.shutil, "disk_usage", lambda p: SimpleNamespace(free=64 * 1024**3)
    )


def test_running_macos_installer_stops_owned_child_at_disk_reserve(
    tmp_path, monkeypatch
):
    import sys
    from types import SimpleNamespace

    mac(monkeypatch)
    monkeypatch.setattr(
        setup.shutil, "disk_usage", lambda p: SimpleNamespace(free=4 * 1024**3)
    )
    children = []
    popen = setup.subprocess.Popen

    def spawn(*args, **kwargs):
        child = popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(setup.subprocess, "Popen", spawn)
    with pytest.raises(ValueError, match="5 GiB"):
        setup._run_install(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            tmp_path / "install.log",
        )
    assert len(children) == 1
    assert children[0].poll() is not None


def test_root_cli_external_models_and_device_are_validated(tmp_path, capsys):
    args = [
        "plan",
        "--root",
        str(tmp_path / "internal"),
        "--models",
        str(tmp_path / "external"),
        "--device",
        "mps",
    ]
    assert setup.main(args) == 0
    config = json.loads(capsys.readouterr().out)["config"]
    assert config["models"] == str(tmp_path / "external")
    assert config["device"] == "mps"
    assert setup.main(["plan", "--root", str(tmp_path), "--models", "relative"]) == 2
    capsys.readouterr()
    assert not list(tmp_path.iterdir())


def test_mps_low_memory_cannot_be_silently_enabled_by_lowering_threshold(tmp_path):
    config = setup.SetupConfig.at_root(tmp_path).model_copy(
        update={"device": "mps", "minimum_memory_gib": 1}
    )
    status = {
        "known": True,
        "available_bytes": 8 * 1024**3,
        "effective_limit_bytes": 8 * 1024**3,
    }
    with pytest.raises(ValueError, match="32 GiB"):
        setup.require_memory(config, status)


def test_macos_install_refuses_unmanaged_and_shared_checkout_lock(
    tmp_path, monkeypatch
):
    from comfy_prompt_cli.native_download import file_lock

    mac(monkeypatch)
    monkeypatch.setattr(setup.platform, "python_version", lambda: "3.12.12")
    config = setup.SetupConfig.at_root(tmp_path)
    with (
        file_lock(config.checkout.with_name(config.checkout.name + ".setup.lock")),
        pytest.raises(ValueError, match="Another setup"),
    ):
        setup.install(config)
    assert not config.venv.exists()
    config.venv.mkdir()
    with pytest.raises(ValueError, match="unmanaged"):
        setup.install(config)


def test_macos_disk_admission_before_writes(tmp_path, monkeypatch):
    from types import SimpleNamespace

    mac(monkeypatch)
    monkeypatch.setattr(setup.platform, "python_version", lambda: "3.12.12")
    monkeypatch.setattr(
        setup.shutil, "disk_usage", lambda p: SimpleNamespace(free=12 * 1024**3)
    )
    with pytest.raises(ValueError, match="5 GiB"):
        setup.install(setup.SetupConfig.at_root(tmp_path))
    assert not list(tmp_path.iterdir())


def test_macos_root_defaults_and_pinned_plan(tmp_path, monkeypatch):
    mac(monkeypatch)
    config = setup.SetupConfig.at_root(tmp_path)
    assert config.device == "mps"
    assert config.runtime_environment == {
        "PYTORCH_ENABLE_MPS_FALLBACK": "1",
        "OMP_NUM_THREADS": "1",
    }
    install = setup.plan(config)["installation"]
    assert install["python"] == "3.12.12"
    assert install["torch"] == "2.14.1"
    assert install["torchvision"] == "0.29.1"
    assert install["torch_index"] == "https://pypi.org/simple"
    assert "torchaudio" not in install
    assert not list(tmp_path.iterdir())


def test_linux_defaults_preserved(tmp_path, monkeypatch):
    monkeypatch.setattr(setup.platform, "system", lambda: "Linux")
    config = setup.SetupConfig.at_root(tmp_path)
    assert config.device == "cuda"
    assert config.runtime_environment == {}
    install = setup.plan(config)["installation"]
    assert install["torch"] == "2.10.0"
    assert install["torchaudio"] == "2.10.0"
    assert install["torch_index"].endswith("cu130")


def test_macos_memory_uses_physical_and_reclaimable_pages(tmp_path, monkeypatch):
    mac(monkeypatch)

    def run(argv, **kw):
        output = (
            str(8 * 1024**3)
            if argv[0] == "/usr/sbin/sysctl"
            else (
                "Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
                "Pages free: 100.\nPages inactive: 200.\nPages speculative: 50.\n"
            )
        )
        return subprocess.CompletedProcess(argv, 0, output, "")

    monkeypatch.setattr(setup.subprocess, "run", run)
    status = setup.memory_status()
    assert status["known"]
    assert status["source"] == "macos-vm-stat"
    assert status["effective_limit_bytes"] == 8 * 1024**3
    assert status["available_bytes"] == 350 * 16384
    with pytest.raises(ValueError, match="memory"):
        setup.require_memory(setup.SetupConfig.at_root(tmp_path), status)
    setup.require_memory(
        setup.SetupConfig.at_root(tmp_path), status, allow_low_memory=True
    )


def test_macos_memory_failure_closed(monkeypatch):
    mac(monkeypatch)
    monkeypatch.setattr(
        setup.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, "bad", ""),
    )
    assert not setup.memory_status()["known"]


@pytest.mark.parametrize(
    "available,tensor,ok",
    [(False, False, False), (True, False, False), (True, True, True)],
)
def test_probe_requires_actual_mps_tensor(tmp_path, monkeypatch, available, tensor, ok):
    mac(monkeypatch)
    config = setup.SetupConfig.at_root(tmp_path)
    config.python.parent.mkdir(parents=True)
    config.python.touch()
    (config.venv / "pyvenv.cfg").touch()
    data = {
        "ok": True,
        "prefix": str(config.venv),
        "base_prefix": "/base",
        "cuda_available": False,
        "mps_available": available,
        "mps_tensor_ok": tensor,
    }

    def run(argv, **kw):
        assert "torch.ones" in argv[-2]
        assert argv[-1] == "mps"
        assert kw["env"]["PYTORCH_ENABLE_MPS_FALLBACK"] == "1"
        return subprocess.CompletedProcess(argv, 0, json.dumps(data), "")

    monkeypatch.setattr(setup.subprocess, "run", run)
    assert setup.probe(config)["ok"] is ok


def test_macos_install_rejects_wrong_python_before_writes(tmp_path, monkeypatch):
    mac(monkeypatch)
    monkeypatch.setattr(setup.platform, "python_version", lambda: "3.14.3")
    config = setup.SetupConfig.at_root(tmp_path)
    with pytest.raises(ValueError, match="3.12.12"):
        setup.install(config)
    assert not config.venv.exists()


def test_macos_install_uses_pypi_constraints_and_real_venv(tmp_path, monkeypatch):
    mac(monkeypatch)
    monkeypatch.setattr(setup.platform, "python_version", lambda: "3.12.12")
    config = setup.SetupConfig.at_root(tmp_path)
    config.checkout.mkdir()
    monkeypatch.setattr(setup, "checkout_status", lambda c: {"ok": True})
    calls = []
    monkeypatch.setattr(setup, "_run_install", lambda argv, log: calls.append(argv))
    setup.install(config)
    assert (config.venv / "pyvenv.cfg").is_file()
    assert "https://pypi.org/simple" in calls[0]
    assert "torch==2.14.1" in calls[0]
    assert "torchvision==0.29.1" in calls[0]
    assert not any("cu130" in str(c) or "torchaudio" in str(c) for c in calls)
    assert "torch==2.14.1" in (config.venv / "native-constraints.txt").read_text()


def test_config_restricts_environment(tmp_path):
    config = setup.SetupConfig.at_root(tmp_path).model_dump(mode="json")
    config.update(device="mps", mps_fallback=False, omp_num_threads=3)
    parsed = setup.SetupConfig.model_validate(config)
    assert parsed.runtime_environment == {
        "PYTORCH_ENABLE_MPS_FALLBACK": "0",
        "OMP_NUM_THREADS": "3",
    }
    with pytest.raises(ValueError):
        setup.SetupConfig.model_validate({**config, "omp_num_threads": 0})
    with pytest.raises(ValueError):
        setup.SetupConfig.model_validate(
            {**config, "environment": {"PYTHONPATH": "/bad"}}
        )
