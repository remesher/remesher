import os
from pathlib import Path

from typer.testing import CliRunner

import comfy_prompt_cli as cli
from comfy_prompt_cli import _clear_worker_output_candidates, _recover_worker_output, app


def test_recover_worker_output_from_direct_docker_output_layout(tmp_path):
    input_dir = tmp_path / "docker" / "input"
    produced = tmp_path / "docker" / "output" / "skin_cleanup" / "robot.glb"
    destination = tmp_path / "requested" / "robot.glb"
    produced.parent.mkdir(parents=True)
    produced.write_bytes(b"validated-glb")

    recovered = _recover_worker_output(
        input_dir=input_dir,
        subfolder="skin_cleanup",
        filename="robot.glb",
        destination=destination,
    )

    assert recovered == produced
    assert destination.read_bytes() == b"validated-glb"


def test_recover_worker_output_from_workspace_comfyui_layout(tmp_path):
    input_dir = tmp_path / "workspace" / "input"
    produced = (
        tmp_path
        / "workspace"
        / "output"
        / "comfyui"
        / "skin_cleanup"
        / "robot.json"
    )
    destination = tmp_path / "requested" / "robot.json"
    produced.parent.mkdir(parents=True)
    produced.write_text("{}")

    recovered = _recover_worker_output(
        input_dir=input_dir,
        subfolder="skin_cleanup",
        filename="robot.json",
        destination=destination,
    )

    assert recovered == produced
    assert destination.read_text() == "{}"


def test_recover_worker_output_ignores_stale_candidate(tmp_path):
    input_dir = tmp_path / "docker" / "input"
    stale = tmp_path / "docker" / "output" / "comfyui" / "skin_cleanup" / "robot.glb"
    fresh = tmp_path / "docker" / "output" / "skin_cleanup" / "robot.glb"
    destination = tmp_path / "requested" / "robot.glb"
    stale.parent.mkdir(parents=True)
    fresh.parent.mkdir(parents=True)
    stale.write_bytes(b"stale")
    fresh.write_bytes(b"fresh")
    os.utime(stale, ns=(100, 100))
    os.utime(fresh, ns=(200, 200))

    recovered = _recover_worker_output(
        input_dir=input_dir,
        subfolder="skin_cleanup",
        filename="robot.glb",
        destination=destination,
    )

    assert recovered == fresh
    assert destination.read_bytes() == b"fresh"


def test_recover_worker_output_does_not_accept_preexisting_destination(tmp_path):
    input_dir = tmp_path / "docker" / "input"
    produced = tmp_path / "docker" / "output" / "skin_cleanup" / "robot.glb"
    produced.parent.mkdir(parents=True)
    produced.write_bytes(b"fresh-output")
    os.utime(produced, ns=(200, 200))
    destination = tmp_path / "requested" / "robot.glb"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"old-output")

    recovered = _recover_worker_output(
        input_dir=input_dir,
        subfolder="skin_cleanup",
        filename="robot.glb",
        destination=destination,
    )

    assert recovered is None
    assert destination.read_bytes() == b"old-output"


def test_skin_cleanup_rejects_existing_output_before_worker(tmp_path, monkeypatch):
    source = tmp_path / "source.glb"
    source.write_bytes(b"source")
    worker = tmp_path / "worker.py"
    worker.write_text("# worker")
    out_dir = tmp_path / "requested"
    out_dir.mkdir()
    (out_dir / "robot.glb").write_bytes(b"existing")
    subprocess_called = False

    def unexpected_subprocess(*args, **kwargs):
        nonlocal subprocess_called
        subprocess_called = True
        raise AssertionError("worker must not run")

    monkeypatch.setattr(cli.subprocess, "run", unexpected_subprocess)

    result = CliRunner().invoke(
        app,
        [
            "skin-cleanup-glb",
            "--input-glb",
            str(source),
            "--output-name",
            "robot",
            "--worker-file",
            str(worker),
            "--input-dir",
            str(tmp_path / "input"),
            "--out-dir",
            str(out_dir),
        ],
    )

    assert result.exit_code != 0
    assert "Refusing to overwrite" in result.output
    assert subprocess_called is False


def test_clear_worker_output_candidates_removes_both_layouts(tmp_path):
    input_dir = tmp_path / "docker" / "input"
    direct = tmp_path / "docker" / "output" / "skin_cleanup" / "robot.glb"
    notebook = (
        tmp_path
        / "docker"
        / "output"
        / "comfyui"
        / "skin_cleanup"
        / "robot.glb"
    )
    for path in (direct, notebook):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"stale")

    _clear_worker_output_candidates(
        input_dir=input_dir,
        subfolder="skin_cleanup",
        filenames=("robot.glb",),
    )

    assert not direct.exists()
    assert not notebook.exists()
