import pytest

from comfy_prompt_cli.native_backend import build_prompt, validate_prompt


def test_v3_combo_model_enum_fails_before_upload():
    graph = {
        "model": {
            "class_type": "LoadMoGeModel",
            "inputs": {"model_name": "missing.safetensors"},
        }
    }
    info = {
        "LoadMoGeModel": {
            "input": {"required": {"model_name": ["COMBO", {"options": []}]}},
            "output": ["MOGE_MODEL"],
        }
    }
    with pytest.raises(ValueError, match="unavailable"):
        validate_prompt(graph, info)
    info["LoadMoGeModel"]["input"]["required"]["model_name"][1]["options"] = [
        "missing.safetensors"
    ]
    validate_prompt(graph, info)


def test_pixal_automatic_horizontal_fov_uses_current_moge_contract():
    graph = build_prompt(
        "wrestler.png", model="pixal3d", no_decimation=True, mesh_repair="solid"
    )
    assert graph["conditioning"]["inputs"]["camera_angle_x"] == ["moge_fov", 0]
    assert graph["moge_fov"]["inputs"] == {
        "moge_geometry": ["moge_inference", 0],
        "axis": "horizontal",
        "unit": "degrees",
    }
    assert graph["moge_inference"]["inputs"] == {
        "moge_model": ["moge_model", 0],
        "image": ["image", 0],
        "resolution_level": 9,
        "fov_x_degrees": 0.0,
        "batch_size": 4,
        "force_projection": True,
        "apply_mask": True,
        "refine_steps": 3,
    }
    assert (
        graph["moge_model"]["inputs"]["model_name"]
        == "moge_2_vitl_normal_fp16.safetensors"
    )
    assert "decimate" not in graph
    assert graph["repair_remesh"]["inputs"]["precluster_max_verts"] == 0


def test_explicit_fov_and_trellis_do_not_run_moge():
    graph = build_prompt("image.png", model="pixal3d", camera_angle=45)
    assert graph["conditioning"]["inputs"]["camera_angle_x"] == 45
    assert not any(k.startswith("moge") for k in graph)
    assert not any(k.startswith("moge") for k in build_prompt("image.png"))
