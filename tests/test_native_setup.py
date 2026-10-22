"""Setup tests never fetch real weights or mutate the acceptance runtime."""

import json
import subprocess
import sys


def test_plan_is_json_read_only_and_contains_pinned_core(tmp_path):
    root = tmp_path / "runtime"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "comfy_prompt_cli.native_setup",
            "plan",
            "--root",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["operation"] == "plan"
    assert report["config"]["models"] == str(root / "models")
    assert report["download_bytes"] == 8512567756
    assert len(report["models"]) == 4
    assert all(
        len(m["sha256"]) == 64 and len(m["revision"]) == 40 for m in report["models"]
    )
    assert report["generation_validated"] is False
    assert not root.exists()


def test_effective_memory_uses_tightest_ancestor_and_current(tmp_path):
    from comfy_prompt_cli.native_setup import memory_status

    proc = tmp_path / "proc"
    proc.mkdir()
    cg = tmp_path / "cg"
    leaf = cg / "parent" / "child"
    leaf.mkdir(parents=True)
    (proc / "meminfo").write_text(
        "MemTotal: 134217728 kB\nMemAvailable: 100663296 kB\n"
    )
    (proc / "self").mkdir()
    (proc / "self/cgroup").write_text("0::/parent/child\n")
    (proc / "self/mountinfo").write_text(f"1 0 0:1 / {cg} rw - cgroup2 cgroup rw\n")
    (cg / "memory.max").write_text("max")
    (cg / "parent/memory.max").write_text(str(4 * 1024**3))
    (cg / "parent/memory.current").write_text(str(1024**3))
    (leaf / "memory.max").write_text("max")
    status = memory_status(proc)
    assert status["effective_limit_bytes"] == 4 * 1024**3
    assert status["available_bytes"] == 3 * 1024**3
    assert status["cgroup_detected"] is True


def test_memory_unknown_fails_closed(tmp_path):
    import pytest

    from comfy_prompt_cli.native_setup import SetupConfig, memory_status, require_memory

    status = memory_status(tmp_path)
    with pytest.raises(ValueError, match="memory"):
        require_memory(SetupConfig.at_root(tmp_path / "runtime"), status)
    require_memory(
        SetupConfig.at_root(tmp_path / "runtime"), status, allow_low_memory=True
    )


def test_download_resume_hash_and_idempotence(tmp_path):
    import hashlib

    import httpx

    from comfy_prompt_cli.native_download import download

    data = b"safe model fixture"
    model = {
        "repo": "Comfy-Org/TRELLIS.2",
        "revision": "a" * 40,
        "path": "vae/fixture.safetensors",
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    target = tmp_path / model["path"]
    target.parent.mkdir()
    target.with_suffix(".safetensors.part").write_bytes(data[:4])
    seen = []

    def respond(request):
        seen.append(request)
        assert request.headers["range"] == "bytes=4-"
        return httpx.Response(
            206,
            headers={"content-range": f"bytes 4-{len(data) - 1}/{len(data)}"},
            content=data[4:],
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert download(model, tmp_path, client=client) == "downloaded"
        assert target.read_bytes() == data
        assert download(model, tmp_path, client=client) == "reused"
    assert len(seen) == 1


def test_download_rejects_corruption_and_redirect_outside_allowlist(tmp_path):
    import hashlib

    import httpx
    import pytest

    from comfy_prompt_cli.native_download import download

    model = {
        "repo": "Comfy-Org/TRELLIS.2",
        "revision": "a" * 40,
        "path": "vae/fixture.safetensors",
        "size": 3,
        "sha256": hashlib.sha256(b"yes").hexdigest(),
    }
    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"bad"))
        ) as client,
        pytest.raises(ValueError, match="SHA256"),
    ):
        download(model, tmp_path, client=client)
    assert not (tmp_path / model["path"]).exists()
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    302, headers={"location": "http://evil.test/file"}
                )
            )
        ) as client,
        pytest.raises(ValueError, match="redirect"),
    ):
        download(model, tmp_path, client=client)


def test_check_and_apply_do_not_install_or_download_without_optins(
    tmp_path, monkeypatch
):
    from comfy_prompt_cli import native_setup as setup

    config = setup.SetupConfig.at_root(tmp_path / "runtime")
    monkeypatch.setattr(
        setup, "probe", lambda c: {"ok": False, "error": "missing venv"}
    )
    monkeypatch.setattr(
        setup,
        "memory_status",
        lambda: {
            "known": True,
            "available_bytes": 64 * 1024**3,
            "effective_limit_bytes": 64 * 1024**3,
        },
    )
    check = setup.check(config)
    assert not check["ready"]
    assert check["missing_model_bytes"] == 8512567756
    assert not config.venv.parent.exists()
    result = setup.apply(config, tmp_path / "setup.json")
    assert not result["ready"]
    assert any("--allow-install" in x for x in result["blockers"])
    assert not config.venv.parent.exists()
    assert not (tmp_path / "setup.json").exists()


def test_product_setup_command_plan(tmp_path):
    from typer.testing import CliRunner

    from comfy_prompt_cli import app

    result = CliRunner().invoke(
        app, ["native-setup", "plan", "--root", str(tmp_path / "runtime")]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["download_bytes"] == 8512567756


def test_config_routes_native_local_and_output(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from comfy_prompt_cli import app, native_backend, native_runtime, native_setup

    cfg = native_setup.SetupConfig.at_root(tmp_path / "runtime")
    path = tmp_path / "config.json"
    path.write_text(cfg.model_dump_json())
    image = tmp_path / "image.png"
    image.write_bytes(b"fixture")
    monkeypatch.setattr(native_setup, "check", lambda *a, **k: {"ready": True})

    class Owner:
        def __init__(self, python, checkout, runs, **kw):
            assert python == cfg.python
            assert checkout == cfg.checkout
            assert runs == cfg.runs
            assert kw["models"] == cfg.models
            self.base_url, self.run_dir = "http://127.0.0.1:12345", cfg.runs

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

    monkeypatch.setattr(native_runtime, "LocalRuntime", Owner)

    def generate(client, image_path, output, **kw):
        assert output == cfg.output
        assert image_path == image
        return []

    monkeypatch.setattr(native_backend, "generate", generate)
    result = CliRunner().invoke(
        app,
        [
            "image-to-glb",
            "--backend",
            "native-local",
            "--native-config",
            str(path),
            "--image",
            str(image),
        ],
    )
    assert result.exit_code == 0, result.output
    conflict = CliRunner().invoke(
        app,
        [
            "image-to-glb",
            "--backend",
            "native-local",
            "--native-config",
            str(path),
            "--native-runs",
            str(tmp_path / "other"),
            "--image",
            str(image),
        ],
    )
    assert conflict.exit_code != 0
    assert "conflict" in conflict.output


def test_install_refuses_existing_unmanaged_venv(tmp_path):
    import pytest

    from comfy_prompt_cli.native_setup import SetupConfig, install

    config = SetupConfig.at_root(tmp_path / "runtime")
    config.venv.mkdir(parents=True)
    sentinel = config.venv / "untouched"
    sentinel.write_text("existing")
    with pytest.raises(ValueError, match="unmanaged"):
        install(config)
    assert sentinel.read_text() == "existing"


def test_setup_cli_check_and_errors_are_json(tmp_path):
    cli = [sys.executable, "-m", "comfy_prompt_cli.native_setup"]
    result = subprocess.run(
        cli + ["check", "--root", str(tmp_path / "runtime")],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["operation"] == "check"
    assert report["ready"] is False
    invalid = subprocess.run(
        cli + ["apply", "--root", "relative", "--allow-download"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert invalid.returncode == 2
    assert json.loads(invalid.stdout)["ok"] is False


def test_apply_memory_block_precedes_side_effects(tmp_path, monkeypatch):
    import pytest

    from comfy_prompt_cli import native_setup as setup

    config = setup.SetupConfig.at_root(tmp_path / "runtime")
    monkeypatch.setattr(
        setup,
        "memory_status",
        lambda: {
            "known": True,
            "available_bytes": 4 * 1024**3,
            "effective_limit_bytes": 4 * 1024**3,
        },
    )
    monkeypatch.setattr(
        setup, "install", lambda c: pytest.fail("installed under unapproved low memory")
    )
    result = setup.apply(
        config, tmp_path / "setup.json", allow_install=True, allow_download=True
    )
    assert not result["ready"]
    assert not config.venv.parent.exists()
