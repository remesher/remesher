from pathlib import Path

from typer.testing import CliRunner

from comfy_prompt_cli import DEFAULT_POSE_GLB_WORKER, DEFAULT_USDZ_WORKER, USDZ_EXTENSIONS, app


def test_usdz_constants_point_to_worker():
    assert USDZ_EXTENSIONS == {".usdz"}
    assert DEFAULT_USDZ_WORKER == Path("docker/demo-jupyter/scripts/glb_to_usdz_worker.py")


def test_pose_glb_constant_points_to_worker():
    assert DEFAULT_POSE_GLB_WORKER == Path("docker/demo-jupyter/scripts/pose_glb_worker.py")


def test_glb_to_usdz_help_is_registered():
    result = CliRunner().invoke(app, ["glb-to-usdz", "--help"])
    assert result.exit_code == 0
    assert "Convert a GLB to USDZ" in result.output
    assert "--glb" in result.output
    assert "--output-name" in result.output


def test_pose_glb_help_is_registered():
    result = CliRunner().invoke(app, ["pose-glb", "--help"])
    assert result.exit_code == 0
    assert "Apply a simple bone-rotation pose JSON" in result.output
    assert "--rigged-glb" in result.output
    assert "--pose-json" in result.output
