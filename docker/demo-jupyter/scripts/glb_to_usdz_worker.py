#!/usr/bin/env python3
"""Isolated Blender/bpy worker for GLB -> USDZ export."""
from __future__ import annotations

import argparse
import json
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
        # Older Blender builds may not expose disable_bone_shape.
        kwargs.pop("disable_bone_shape", None)
        bpy.ops.import_scene.gltf(**kwargs)
    bpy.context.view_layer.update()
    return _counts(bpy)


def _export_usdz(bpy: Any, output_usdz: Path, export_animation: bool) -> None:
    output_usdz.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.usd_export(
        filepath=str(output_usdz),
        selected_objects_only=False,
        export_animation=export_animation,
    )


def _validate_usdz(bpy: Any, output_usdz: Path) -> dict[str, Any]:
    _clear_scene(bpy)
    bpy.ops.wm.usd_import(filepath=str(output_usdz))
    bpy.context.view_layer.update()
    return _counts(bpy)


def convert_glb_to_usdz(
    input_glb_path: str,
    output_usdz_path: str,
    *,
    summary_json: str | None = None,
    validate: bool = True,
    disable_bone_shape: bool = True,
    export_animation: bool = True,
) -> dict[str, Any]:
    import bpy  # noqa: PLC0415

    input_glb = Path(input_glb_path)
    output_usdz = Path(output_usdz_path)
    if not input_glb.exists():
        raise FileNotFoundError(f"Input GLB not found: {input_glb}")

    _clear_scene(bpy)
    source_counts = _import_glb(bpy, input_glb, disable_bone_shape=disable_bone_shape)
    _export_usdz(bpy, output_usdz, export_animation=export_animation)

    summary: dict[str, Any] = {
        "input_glb": str(input_glb),
        "output_usdz": str(output_usdz),
        "output_exists": output_usdz.exists(),
        "output_size_bytes": output_usdz.stat().st_size if output_usdz.exists() else 0,
        "validate": validate,
        "disable_bone_shape": disable_bone_shape,
        "export_animation": export_animation,
        "source": source_counts,
    }
    if validate:
        try:
            summary["reimport"] = _validate_usdz(bpy, output_usdz)
        except Exception as exc:  # noqa: BLE001 - report validation failure in summary before re-raising.
            summary["validation_error"] = repr(exc)
            if summary_json:
                Path(summary_json).parent.mkdir(parents=True, exist_ok=True)
                Path(summary_json).write_text(json.dumps(summary, indent=2) + "\n")
            raise

    if summary_json:
        Path(summary_json).parent.mkdir(parents=True, exist_ok=True)
        Path(summary_json).write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert a GLB to USDZ with Blender/bpy.")
    parser.add_argument("input_glb")
    parser.add_argument("output_usdz")
    parser.add_argument("--summary-json", default=None)
    parser.add_argument("--no-validate", action="store_true")
    parser.add_argument("--keep-bone-shapes", action="store_true")
    parser.add_argument("--no-animation", action="store_true")
    args = parser.parse_args()
    convert_glb_to_usdz(
        args.input_glb,
        args.output_usdz,
        summary_json=args.summary_json,
        validate=not args.no_validate,
        disable_bone_shape=not args.keep_bone_shapes,
        export_animation=not args.no_animation,
    )


if __name__ == "__main__":
    main()
