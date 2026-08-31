import os
from pathlib import Path

from comfy_prompt_cli import _recover_worker_output


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
        not_before_ns=150,
    )

    assert recovered == fresh
    assert destination.read_bytes() == b"fresh"


def test_recover_worker_output_does_not_accept_preexisting_destination(tmp_path):
    destination = tmp_path / "requested" / "robot.glb"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"old-output")

    recovered = _recover_worker_output(
        input_dir=tmp_path / "docker" / "input",
        subfolder="skin_cleanup",
        filename="robot.glb",
        destination=destination,
        not_before_ns=150,
    )

    assert recovered is None
    assert destination.read_bytes() == b"old-output"
