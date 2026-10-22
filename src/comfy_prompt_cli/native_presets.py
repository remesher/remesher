"""Explicit native job presets; omission retains historical CLI defaults."""

PRESETS = {
    "quality-1536-solid768": {
        "native_shape_resolution": 1536,
        "native_atlas_resolution": 4096,
        "mesh_repair": "solid",
        "repair_resolution": 768,
        "repair_max_perimeter": 0.03,
        "repair_drop_small_components": 0.005,
        "no_decimation": True,
    },
    "fast": {
        "native_shape_resolution": 512,
        "native_atlas_resolution": 1024,
        "mesh_repair": "none",
        "repair_resolution": 512,
        "repair_max_perimeter": 0.03,
        "repair_drop_small_components": 0.005,
        "no_decimation": False,
        "target_face_num": 80000,
    },
}


def resolve_preset(name, explicit):
    """Reject contradictions, including a face budget for the uncapped preset."""
    if not isinstance(name, str) or name not in PRESETS:
        raise ValueError("native preset must be quality-1536-solid768 or fast")
    values = PRESETS[name]
    for key, value in explicit.items():
        if key in values and (type(value) is not type(values[key]) or value != values[key]):
            raise ValueError(f"native preset {name} conflicts with explicit {key}")
        if key == "target_face_num" and values["no_decimation"]:
            raise ValueError(f"native preset {name} conflicts with target_face_num")
    return dict(values)
