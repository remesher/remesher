"""Real process and loopback protocol regressions; no installers or inference."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from comfy_prompt_cli import native_setup
from comfy_prompt_cli.native_runtime import LocalRuntime


@pytest.mark.parametrize("previous", [signal.SIG_DFL, signal.SIG_IGN])
def test_runtime_defers_sigterm_until_spawn_handle_is_owned(
    tmp_path, monkeypatch, previous
):
    original = subprocess.Popen
    children = []

    def spawn(*args, **kwargs):
        child = original(
            [sys.executable, "-c", "import time; time.sleep(30)"], **kwargs
        )
        children.append(child)
        os.kill(os.getpid(), signal.SIGTERM)
        os.kill(os.getpid(), signal.SIGTERM)
        return child

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "main.py").write_text("# fixture\n")
    owner = LocalRuntime(
        Path(sys.executable), checkout, tmp_path / "runs", device="cpu"
    )
    original_handler = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, previous)
    monkeypatch.setattr(native_setup.subprocess, "Popen", spawn)
    try:
        with pytest.raises(SystemExit) as caught:
            owner.__enter__()
        assert caught.value.code == 143
        assert len(children) == 1 and children[0].poll() is not None
        with pytest.raises(ChildProcessError):
            os.waitpid(children[0].pid, os.WNOHANG)
        assert owner.process is children[0]
        assert owner.closed and owner.log is not None and owner.log.closed
        assert signal.getsignal(signal.SIGTERM) is previous
        owner.close()
        assert signal.getsignal(signal.SIGTERM) is previous
    finally:
        signal.signal(signal.SIGTERM, original_handler)
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=2)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux installer ownership")
@pytest.mark.parametrize(
    "ignore_term", [False, True], ids=["cooperative", "kill-escalation"]
)
def test_install_sigterm_unwinds_reaps_and_restores_handler(tmp_path, ignore_term):
    log = tmp_path / "install.log"
    result = tmp_path / "result.json"
    mutator = """
import json, os, signal, subprocess, sys, time
if sys.argv[2] == 'True':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
grandchild = subprocess.Popen([sys.executable, '-c', '''
import signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
while True:
    with open(sys.argv[1], 'ab') as f:
        f.write(b'x')
    time.sleep(.02)
''', sys.argv[1] + '.descendant'])
print(json.dumps([os.getpid(), grandchild.pid]), flush=True)
while True:
    with open(sys.argv[1], 'ab') as f:
        f.write(b'x')
    time.sleep(.02)
"""
    parent_code = """
import json, os, signal, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from comfy_prompt_cli.native_setup import _run_install
previous = signal.SIG_DFL if sys.argv[6] == 'False' else (lambda *args: None)
signal.signal(signal.SIGTERM, previous)
try:
    _run_install([sys.executable, '-c', sys.argv[4], sys.argv[5], sys.argv[6]], Path(sys.argv[2]))
except SystemExit as exc:
    restored = signal.getsignal(signal.SIGTERM) is previous
    try:
        os.waitpid(-1, os.WNOHANG)
        reaped = False
    except ChildProcessError:
        reaped = True
    Path(sys.argv[3]).write_text(json.dumps({'code': exc.code, 'restored': restored, 'reaped': reaped}))
    raise
"""
    heartbeat = tmp_path / "heartbeat"
    parent = subprocess.Popen(
        [
            sys.executable,
            "-c",
            parent_code,
            str(Path(native_setup.__file__).parent.parent),
            str(log),
            str(result),
            mutator,
            str(heartbeat),
            str(ignore_term),
        ],
        start_new_session=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    child_pid = descendant_pid = None
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True
    )
    descendant_heartbeat = tmp_path / "heartbeat.descendant"
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if (
                log.exists()
                and log.read_text().strip()
                and heartbeat.exists()
                and descendant_heartbeat.exists()
            ):
                child_pid, descendant_pid = json.loads(log.read_text().strip())
                break
            time.sleep(0.02)
        assert child_pid is not None, "installer fixture never became ready"
        started = time.monotonic()
        parent.terminate()
        if ignore_term:
            time.sleep(0.1)
            parent.terminate()  # repeated cancellation must not abort cleanup
        _stdout, stderr = parent.communicate(timeout=8)
        assert result.exists(), (
            f"SIGTERM bypassed unwind: {parent.returncode}, {stderr!r}"
        )
        assert json.loads(result.read_text()) == {
            "code": 143,
            "restored": True,
            "reaped": True,
        }
        assert parent.returncode == 143
        assert time.monotonic() - started < 7
        assert not Path(f"/proc/{child_pid}").exists(), "installer was not reaped"
        sizes = [p.stat().st_size for p in (heartbeat, descendant_heartbeat)]
        time.sleep(0.1)
        assert [p.stat().st_size for p in (heartbeat, descendant_heartbeat)] == sizes, (
            "installer group is still mutating"
        )
        descendant_stat = Path(f"/proc/{descendant_pid}/stat")
        assert (
            not descendant_stat.exists()
            or descendant_stat.read_text().split()[2] == "Z"
        )
        assert unrelated.poll() is None, "cleanup affected an unowned process"
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=2)
        if parent.poll() is None:
            parent.kill()
        parent.communicate(timeout=2)
        if child_pid is not None:
            try:
                os.killpg(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_install_restores_handler_after_success_and_failure(tmp_path):
    previous = signal.getsignal(signal.SIGTERM)
    for code in (0, 7):
        try:
            native_setup._run_install(
                [sys.executable, "-c", f"raise SystemExit({code})"], tmp_path / "log"
            )
        except RuntimeError:
            assert code == 7
        assert signal.getsignal(signal.SIGTERM) is previous


def test_install_restores_handler_when_spawn_fails(tmp_path):
    previous = signal.getsignal(signal.SIGTERM)
    with pytest.raises(FileNotFoundError):
        native_setup._run_install(
            [str(tmp_path / "missing-executable")], tmp_path / "log"
        )
    assert signal.getsignal(signal.SIGTERM) is previous


def test_install_defers_sigterm_until_spawn_handle_is_owned(tmp_path, monkeypatch):
    original = subprocess.Popen
    children = []

    def spawn(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        os.kill(os.getpid(), signal.SIGTERM)
        return child

    original_handler = signal.getsignal(signal.SIGTERM)

    def previous(signum, frame):
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, previous)
    monkeypatch.setattr(native_setup.subprocess, "Popen", spawn)
    try:
        with pytest.raises(SystemExit) as caught:
            native_setup._run_install(
                [sys.executable, "-c", "import time; time.sleep(30)"], tmp_path / "log"
            )
        assert caught.value.code == 143
        assert len(children) == 1 and children[0].poll() is not None
        with pytest.raises(ChildProcessError):
            os.waitpid(children[0].pid, os.WNOHANG)
        assert signal.getsignal(signal.SIGTERM) is previous
    finally:
        signal.signal(signal.SIGTERM, original_handler)
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=2)
