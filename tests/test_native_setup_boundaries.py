"""Hermetic setup safety boundaries; never real model installation/inference."""

import hashlib
import json
import subprocess
import sys

import httpx
import pytest

from comfy_prompt_cli import native_setup as setup
from comfy_prompt_cli.native_download import download, file_lock


@pytest.mark.parametrize(
    "field,value",
    [
        ("venv", "relative"),
        ("models", "/"),
        ("output", "/a/../b"),
        ("device", "mps"),
        ("schema_version", 2),
        ("url", "https://evil.test"),
        ("minimum_memory_gib", 0),
    ],
)
def test_config_rejects_unsupported_values(tmp_path, field, value):
    config = setup.SetupConfig.at_root(tmp_path).model_dump(mode="json")
    config[field] = value
    with pytest.raises(ValueError):
        setup.SetupConfig.model_validate(config)


def model(data=b"abcdef"):
    return {
        "repo": "Comfy-Org/TRELLIS.2",
        "revision": "b" * 40,
        "path": "vae/fixture.safetensors",
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def test_ignored_range_restarts_and_invalid_range_never_promotes(tmp_path):
    item = model()
    part = tmp_path / (item["path"] + ".part")
    part.parent.mkdir()
    part.write_bytes(b"abc")
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    206, headers={"content-range": "bytes 0-5/6"}, content=b"abcdef"
                )
            )
        ) as client,
        pytest.raises(ValueError, match="Content-Range"),
    ):
        download(item, tmp_path, client=client)
    assert part.read_bytes() == b"abc"
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"abcdef"))
    ) as client:
        assert download(item, tmp_path, client=client) == "downloaded"
    assert (tmp_path / item["path"]).read_bytes() == b"abcdef"


def test_short_body_retries_from_retained_offset(tmp_path):
    item = model()
    requests = []

    def respond(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, content=b"abc")
        assert request.headers["range"] == "bytes=3-"
        return httpx.Response(
            206, headers={"content-range": "bytes 3-5/6"}, content=b"def"
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert download(item, tmp_path, client=client) == "downloaded"
    assert len(requests) == 2


def test_download_bounds_symlinks_and_concurrent_ownership(tmp_path):
    item = model()
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, content=b"abcdefEXCESS")
            )
        ) as client,
        pytest.raises(ValueError, match="exceeds"),
    ):
        download(item, tmp_path, client=client)
    target = tmp_path / item["path"]
    assert not target.exists()
    with (
        file_lock(target.with_suffix(target.suffix + ".lock")),
        pytest.raises(ValueError, match="Another setup"),
    ):
        download(item, tmp_path)
    elsewhere = tmp_path / "protected"
    elsewhere.write_bytes(b"original")
    target.symlink_to(elsewhere)
    with pytest.raises(ValueError, match="symlink"):
        download(item, tmp_path)
    assert elsewhere.read_bytes() == b"original"


def test_cgroup_v1_mount_root_and_ancestor_limits(tmp_path):
    proc = tmp_path / "proc"
    (proc / "self").mkdir(parents=True)
    cg = tmp_path / "cg"
    (cg / "child").mkdir(parents=True)
    (proc / "meminfo").write_text("MemTotal: 90000000 kB\nMemAvailable: 80000000 kB\n")
    (proc / "self/cgroup").write_text("4:memory:/tenant/child\n")
    (proc / "self/mountinfo").write_text(
        f"1 0 0:1 /tenant {cg} rw - cgroup memory rw,memory\n"
    )
    for directory, limit, current in [(cg, 4000, 1000), (cg / "child", 8000, 100)]:
        (directory / "memory.limit_in_bytes").write_text(str(limit))
        (directory / "memory.usage_in_bytes").write_text(str(current))
    status = setup.memory_status(proc)
    assert status["known"]
    assert status["effective_limit_bytes"] == 4000
    assert status["available_bytes"] == 3000


def test_no_optin_flags_in_plan_and_parser_errors_are_json(capsys):
    assert setup.main(["plan", "--root", "/unused", "--allow-install"]) == 2
    assert "only by apply" in json.loads(capsys.readouterr().out)["error"]
    assert setup.main(["apply", "--root", "/unused", "--url", "https://evil.test"]) == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_apply_reuse_persists_config_but_not_memory_override(tmp_path, monkeypatch):
    config = setup.SetupConfig.at_root(tmp_path / "runtime")
    monkeypatch.setattr(
        setup,
        "check",
        lambda *a, **kw: {
            "ready": True,
            "memory": {"known": False},
            "capabilities": {"ok": True},
            "checkout": {"ok": True},
        },
    )
    monkeypatch.setattr(setup, "install", lambda c: pytest.fail("unexpected install"))
    path = tmp_path / "config.json"
    report = setup.apply(config, path, allow_install=True, allow_low_memory=True)
    assert report["ready"]
    assert setup.load_config(path) == config
    assert "allow_low_memory" not in json.loads(path.read_text())


def test_installer_commands_use_owned_venv_and_preserve_torch_pin(
    tmp_path, monkeypatch
):
    config = setup.SetupConfig.at_root(tmp_path / "runtime")
    config.checkout.mkdir(parents=True)
    (config.checkout / "requirements.txt").write_text("fixture")
    # Real venv and identity check; replace network package actions only.
    monkeypatch.setattr(setup, "checkout_status", lambda c: {"ok": True})
    calls = []
    monkeypatch.setattr(setup, "_run_install", lambda argv, log: calls.append(argv))
    setup.install(config)
    assert (config.venv / "pyvenv.cfg").is_file()
    assert all(argv[0] == str(config.python) for argv in calls)
    assert all("--isolated" in argv for argv in calls)
    assert "--require-virtualenv" in calls[0]
    assert "torch==2.10.0" in calls[0]
    assert "https://download.pytorch.org/whl/cu130" in calls[0]
    assert "torch==2.10.0" in (config.venv / "native-constraints.txt").read_text()
    assert (
        "include-system-site-packages = false"
        in (config.venv / "pyvenv.cfg").read_text()
    )


def test_install_runner_redirects_stdout_and_fails_closed(tmp_path):
    log = tmp_path / "install.log"
    setup._run_install([sys.executable, "-c", "print('fixture installer')"], log)
    assert log.read_text().strip() == "fixture installer"
    with pytest.raises(RuntimeError, match="failed"):
        setup._run_install([sys.executable, "-c", "raise SystemExit(7)"], log)


def test_resume_disk_budget_counts_only_remaining_bytes(tmp_path, monkeypatch):
    config = setup.SetupConfig.at_root(tmp_path / "runtime")
    item = model()
    monkeypatch.setitem(setup.MANIFEST, "models", [item])
    partial = config.models / (item["path"] + ".part")
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b"abc")
    report = setup.check(config, allow_low_memory=True)
    assert report["additional_model_bytes"] == 3


def test_pinned_checkout_rejects_dirty_tree(tmp_path, monkeypatch):
    config = setup.SetupConfig.at_root(tmp_path / "runtime")
    config.checkout.mkdir(parents=True)
    requirements = config.checkout / "requirements.txt"
    requirements.write_text("fixture requirements\n")
    for args in [
        ["init"],
        ["add", "."],
        [
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-m",
            "fixture",
        ],
    ]:
        subprocess.run(
            ["git", "-C", str(config.checkout), *args], check=True, capture_output=True
        )
    head = subprocess.run(
        ["git", "-C", str(config.checkout), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    monkeypatch.setitem(setup.MANIFEST, "comfy_revision", head)
    monkeypatch.setattr(
        setup,
        "REQUIREMENTS_SHA256",
        hashlib.sha256(requirements.read_bytes()).hexdigest(),
    )
    assert setup.checkout_status(config)["ok"]
    requirements.write_text("changed")
    assert not setup.checkout_status(config)["ok"]
