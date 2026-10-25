"""Config publication stays private, atomic, and a no-op on safe reuse."""

import os
import stat

import pytest

from comfy_prompt_cli import native_setup as setup


@pytest.fixture
def ready_config(tmp_path, monkeypatch):
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
    return config, tmp_path / "config.json"


def test_identical_private_config_is_not_written(ready_config, monkeypatch):
    config, path = ready_config
    setup.apply(config, path, allow_low_memory=True)
    before = path.stat()
    content = path.read_bytes()
    monkeypatch.setattr(
        setup.tempfile, "NamedTemporaryFile", lambda **kw: pytest.fail("unexpected write")
    )
    report = setup.apply(config, path, allow_low_memory=True)
    after = path.stat()
    assert report["ready"]
    assert report["config_path"] == str(path)
    assert path.read_bytes() == content
    assert (after.st_ino, after.st_mtime_ns, after.st_mode) == (
        before.st_ino, before.st_mtime_ns, before.st_mode
    )


@pytest.mark.parametrize("mode", [0o644, 0o666, 0o400])
def test_identical_config_still_gets_private_publication_mode(ready_config, mode):
    config, path = ready_config
    path.write_text(config.model_dump_json(indent=2) + "\n")
    path.chmod(mode)
    setup.apply(config, path, allow_low_memory=True)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_identical_hardlinked_config_is_detached(ready_config):
    config, path = ready_config
    setup.apply(config, path, allow_low_memory=True)
    alias = path.with_name("alias.json")
    os.link(path, alias)
    setup.apply(config, path, allow_low_memory=True)
    assert path.stat().st_ino != alias.stat().st_ino
    assert path.read_bytes() == alias.read_bytes()


@pytest.mark.parametrize("kind", ["file", "parent", "dangling"])
def test_identical_config_never_bypasses_symlink_refusal(ready_config, kind):
    config, path = ready_config
    target = path.with_name("target.json")
    target.write_text(config.model_dump_json(indent=2) + "\n")
    target.chmod(0o600)
    before = target.stat()
    if kind == "parent":
        parent = path.parent / "linked"
        parent.symlink_to(path.parent, target_is_directory=True)
        path = parent / target.name
    else:
        path.symlink_to(target if kind == "file" else path.with_name("missing"))
    with pytest.raises(ValueError, match="symlink"):
        setup.apply(config, path, allow_low_memory=True)
    assert target.stat() == before


@pytest.mark.parametrize("fail_replace", [False, True])
def test_changed_config_uses_fsynced_private_atomic_replace(
    ready_config, monkeypatch, fail_replace
):
    config, path = ready_config
    old = b"old config\n"
    path.write_bytes(old)
    inode = path.stat().st_ino
    fsync = setup.os.fsync
    replace = setup.os.replace
    calls = []

    def record_fsync(fd):
        calls.append("fsync")
        fsync(fd)

    def record_replace(source, destination):
        assert calls == ["fsync"]
        assert destination == path
        assert path.read_bytes() == old
        assert source.read_bytes() == (config.model_dump_json(indent=2) + "\n").encode()
        assert stat.S_IMODE(source.stat().st_mode) == 0o600
        calls.append("replace")
        if fail_replace:
            raise OSError("fixture publication failure")
        replace(source, destination)

    monkeypatch.setattr(setup.os, "fsync", record_fsync)
    monkeypatch.setattr(setup.os, "replace", record_replace)
    if fail_replace:
        with pytest.raises(OSError, match="publication failure"):
            setup.apply(config, path, allow_low_memory=True)
        assert path.read_bytes() == old
        assert path.stat().st_ino == inode
    else:
        setup.apply(config, path, allow_low_memory=True)
        assert setup.load_config(path) == config
        assert path.stat().st_ino != inode
    assert calls == ["fsync", "replace"]
    assert not list(path.parent.glob(".native-setup-*"))
