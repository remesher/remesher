#!/usr/bin/env python3
"""Isolated Blender/bpy worker for applying a simple pose to a rigged GLB."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def _clear_scene(bpy: Any) -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action, do_unlink=True)


def _counts(bpy: Any) -> dict[str, Any]:
    objects = list(bpy.context.scene.objects)
    meshes = [obj for obj in objects if obj.type == "MESH"]
    armatures = [obj for obj in objects if obj.type == "ARMATURE"]
    return {
        "objects": len(objects),
        "meshes": len(meshes),
        "armatures": len(armatures),
        "materials": len(bpy.data.materials),
        "images": len(bpy.data.images),
        "actions": len(bpy.data.actions),
        "mesh_names": [obj.name for obj in meshes[:20]],
        "armature_names": [obj.name for obj in armatures[:20]],
        "action_names": [action.name for action in list(bpy.data.actions)[:20]],
    }


def _import_glb(bpy: Any, input_glb: Path, disable_bone_shape: bool) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"filepath": str(input_glb)}
    if disable_bone_shape:
        kwargs["disable_bone_shape"] = True
    try:
        bpy.ops.import_scene.gltf(**kwargs)
    except TypeError:
        kwargs.pop("disable_bone_shape", None)
        bpy.ops.import_scene.gltf(**kwargs)
    bpy.context.view_layer.update()
    return _counts(bpy)


def _find_armature(bpy: Any) -> Any:
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    if not armatures:
        raise ValueError("No armature found in rigged GLB")
    # Prefer the armature with the most pose bones if multiple helpers exist.
    return max(armatures, key=lambda obj: len(getattr(obj.pose, "bones", [])))


def _pose_entries(raw_pose: Any) -> dict[str, dict[str, Any]]:
    if isinstance(raw_pose, dict) and isinstance(raw_pose.get("bones"), dict):
        raw_pose = raw_pose["bones"]
    if not isinstance(raw_pose, dict):
        raise ValueError("Pose JSON must be an object or {'bones': {...}}")
    entries: dict[str, dict[str, Any]] = {}
    for bone_name, spec in raw_pose.items():
        if not isinstance(bone_name, str) or not isinstance(spec, dict):
            continue
        entries[bone_name] = spec
    return entries


def _rotation_radians(spec: dict[str, Any]) -> tuple[float, float, float] | None:
    value = spec.get("rotation_euler")
    if value is None:
        value = spec.get("rotation_radians")
    degrees = False
    if value is None:
        value = spec.get("rotation_degrees")
        degrees = True
    if value is None:
        xyz = [spec.get(axis) for axis in ("x", "y", "z")]
        if all(v is not None for v in xyz):
            value = [v for v in xyz if v is not None]
            degrees = bool(spec.get("degrees", True))
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"Rotation must be a 3-item array, got {value!r}")
    floats = tuple(float(v) for v in value)
    if degrees:
        floats = tuple(math.radians(v) for v in floats)
    return floats  # type: ignore[return-value]


def _apply_pose(bpy: Any, armature: Any, pose: dict[str, dict[str, Any]]) -> dict[str, Any]:
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    applied: list[str] = []
    missing: list[str] = []
    skipped: list[str] = []
    for bone_name, spec in pose.items():
        pose_bone = armature.pose.bones.get(bone_name)
        if pose_bone is None:
            missing.append(bone_name)
            continue
        rotation = _rotation_radians(spec)
        if rotation is None:
            skipped.append(bone_name)
            continue
        pose_bone.rotation_mode = str(spec.get("rotation_mode", "XYZ"))
        pose_bone.rotation_euler = rotation
        applied.append(bone_name)
    bpy.context.view_layer.update()
    return {
        "armature": armature.name,
        "applied_bones": applied,
        "missing_bones": missing,
        "skipped_bones": skipped,
        "available_bone_count": len(armature.pose.bones),
    }


def _export_glb(bpy: Any, output_glb: Path, export_animation: bool) -> None:
    output_glb.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(output_glb),
        export_format="GLB",
        export_animations=export_animation,
    )


def _validate_glb(bpy: Any, output_glb: Path, disable_bone_shape: bool) -> dict[str, Any]:
    _clear_scene(bpy)
    return _import_glb(bpy, output_glb, disable_bone_shape=disable_bone_shape)


def pose_glb(
    input_glb_path: str,
    pose_json_path: str,
    output_glb_path: str,
    *,
    summary_json: str | None = None,
    validate: bool = True,
    disable_bone_shape: bool = True,
    export_animation: bool = False,
) -> dict[str, Any]:
    import bpy  # noqa: PLC0415

    input_glb = Path(input_glb_path)
    pose_json = Path(pose_json_path)
    output_glb = Path(output_glb_path)
    if not input_glb.exists():
        raise FileNotFoundError(f"Input GLB not found: {input_glb}")
    if not pose_json.exists():
        raise FileNotFoundError(f"Pose JSON not found: {pose_json}")

    raw_pose = json.loads(pose_json.read_text())
    pose = _pose_entries(raw_pose)
    if not pose:
        raise ValueError("Pose JSON did not contain any bone rotations")

    _clear_scene(bpy)
    source_counts = _import_glb(bpy, input_glb, disable_bone_shape=disable_bone_shape)
    armature = _find_armature(bpy)
    pose_result = _apply_pose(bpy, armature, pose)
    if not pose_result["applied_bones"]:
        raise ValueError("No pose rotations were applied; check bone names in pose JSON")
    _export_glb(bpy, output_glb, export_animation=export_animation)

    summary: dict[str, Any] = {
        "input_glb": str(input_glb),
        "pose_json": str(pose_json),
        "output_glb": str(output_glb),
        "output_exists": output_glb.exists(),
        "output_size_bytes": output_glb.stat().st_size if output_glb.exists() else 0,
        "validate": validate,
        "disable_bone_shape": disable_bone_shape,
        "export_animation": export_animation,
        "source": source_counts,
        "pose": pose_result,
    }
    if validate:
        summary["reimport"] = _validate_glb(bpy, output_glb, disable_bone_shape=disable_bone_shape)

    if summary_json:
        Path(summary_json).parent.mkdir(parents=True, exist_ok=True)
        Path(summary_json).write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply pose JSON rotations to a rigged GLB with Blender/bpy.")
    parser.add_argument("input_glb")
    parser.add_argument("pose_json")
    parser.add_argument("output_glb")
    parser.add_argument("--summary-json", default=None)
    parser.add_argument("--no-validate", action="store_true")
    parser.add_argument("--keep-bone-shapes", action="store_true")
    parser.add_argument("--export-animation", action="store_true")
    args = parser.parse_args()
    pose_glb(
        args.input_glb,
        args.pose_json,
        args.output_glb,
        summary_json=args.summary_json,
        validate=not args.no_validate,
        disable_bone_shape=not args.keep_bone_shapes,
        export_animation=args.export_animation,
    )


if __name__ == "__main__":
    main()
