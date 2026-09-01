from comfy_prompt_cli import _docker_bpy_exec_prefix


def test_docker_bpy_exec_clears_inherited_open3d_preload():
    assert _docker_bpy_exec_prefix("comfy3d-arm64") == [
        "docker",
        "exec",
        "-e",
        "LD_PRELOAD=",
        "--",
        "comfy3d-arm64",
    ]
