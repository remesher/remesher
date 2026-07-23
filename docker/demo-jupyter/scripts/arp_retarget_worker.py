"""Isolated Auto-Rig Pro retarget worker for Mixamo FBX -> rigged GLB.

This script is launched as a subprocess by ComfyUI nodes. Keeping bpy and
Auto-Rig Pro imports inside this process prevents Blender/ARP failures from
terminating the ComfyUI server process.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _ensure_repo_on_path() -> None:
    repo_root = _repo_root()
    comfy_root = repo_root.parents[1]
    for path in (comfy_root, repo_root, repo_root / "nodes"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))


def _ensure_auto_rig_pro_on_path() -> Path | None:
    """Add the bundled Auto-Rig Pro addon parent to sys.path when available."""
    candidates = [
        Path("/app/comfy/custom_nodes/ComfyUI-UniRig/third_party"),
        Path("/workspace/ComfyUI/custom_nodes/ComfyUI-UniRig/third_party"),
    ]
    for candidate in candidates:
        if (candidate / "auto_rig_pro").exists():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            return candidate / "auto_rig_pro"
    return None


def _action_summary(action) -> dict | None:
    if action is None:
        return None
    data = {"name": action.name, "range": list(action.frame_range)}
    if hasattr(action, "fcurves"):
        data["fcurves"] = len(action.fcurves)
    if hasattr(action, "slots"):
        data["slots"] = len(action.slots)
    if hasattr(action, "layers"):
        data["layers"] = len(action.layers)
    return data


def _pose_delta(bpy, armature, action, bone_name: str, frame_a: int, frame_b: int) -> float | None:
    if bone_name not in armature.pose.bones:
        return None
    armature.animation_data_create()
    armature.animation_data.action = action
    bpy.context.scene.frame_set(frame_a)
    bpy.context.view_layer.update()
    matrix_a = armature.pose.bones[bone_name].matrix.copy()
    bpy.context.scene.frame_set(frame_b)
    bpy.context.view_layer.update()
    matrix_b = armature.pose.bones[bone_name].matrix.copy()
    return max(abs(matrix_a[r][c] - matrix_b[r][c]) for r in range(4) for c in range(4))


def _select_target_for_export(bpy, target) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH" and obj.find_armature() == target:
            obj.select_set(True)
    bpy.context.view_layer.objects.active = target


def _remove_source_objects(bpy, source) -> list[str]:
    removed = []
    for obj in list(bpy.context.scene.objects):
        if obj == source or (obj.type == "MESH" and obj.find_armature() == source):
            removed.append(obj.name)
            bpy.data.objects.remove(obj, do_unlink=True)
    return removed


def _remove_non_target_actions(bpy, target_action) -> list[str]:
    removed = []
    for action in list(bpy.data.actions):
        if action != target_action:
            removed.append(action.name)
            bpy.data.actions.remove(action, do_unlink=True)
    return removed


def _find_target_armature(bpy):
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    if len(armatures) != 1:
        raise RuntimeError(f"Expected exactly one target armature after GLB import, found {[obj.name for obj in armatures]}")
    return armatures[0]


def _find_source_armature(bpy, target):
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE" and obj != target]
    if len(armatures) != 1:
        raise RuntimeError(f"Expected exactly one source armature after FBX import, found {[obj.name for obj in armatures]}")
    return armatures[0]


def retarget_mixamo_to_glb(
    rigged_glb_path: str,
    animation_fbx_path: str,
    output_glb_path: str,
    *,
    frame_start: int | None = None,
    frame_end: int | None = None,
    validate: bool = True,
) -> dict:
    _ensure_repo_on_path()
    import bpy  # noqa: PLC0415

    result: dict = {
        "rigged_glb_path": rigged_glb_path,
        "animation_fbx_path": animation_fbx_path,
        "output_glb_path": output_glb_path,
    }
    rigged_glb = Path(rigged_glb_path)
    animation_fbx = Path(animation_fbx_path)
    output_glb = Path(output_glb_path)
    if not rigged_glb.exists():
        raise FileNotFoundError(f"Rigged GLB not found: {rigged_glb}")
    if not animation_fbx.exists():
        raise FileNotFoundError(f"Animation FBX not found: {animation_fbx}")
    output_glb.parent.mkdir(parents=True, exist_ok=True)

    # Start from a controlled scene before registering ARP. Some ARP modules
    # inspect bpy.context.active_object at import/register time and assume an
    # armature with .data.collections_all. Create a temporary armature to satisfy
    # that import-time reset hook, then delete it before importing assets.
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    bpy.ops.object.armature_add()
    temp_armature = bpy.context.active_object
    temp_armature.name = "__arp_enable_dummy_armature__"
    bpy.context.view_layer.objects.active = temp_armature
    temp_armature.select_set(True)
    try:
        bpy.ops.object.mode_set(mode="POSE")
    except Exception:
        pass

    # Register ARP through Blender's addon API. Direct auto_rig_pro.register()
    # misses addon preferences in headless bpy and fails before scene properties.
    result["auto_rig_pro_path"] = str(_ensure_auto_rig_pro_on_path() or "")
    bpy.ops.preferences.addon_enable(module="auto_rig_pro")
    scn = bpy.context.scene
    result["addon_enabled"] = True

    try:
        bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()

    bpy.ops.import_scene.gltf(filepath=str(rigged_glb))
    target = _find_target_armature(bpy)
    result["target_armature"] = target.name
    result["target_scale"] = list(target.scale)
    result["target_bone_count"] = len(target.data.bones)

    bpy.ops.import_scene.fbx(filepath=str(animation_fbx))
    source = _find_source_armature(bpy, target)
    result["source_armature"] = source.name
    result["source_scale"] = list(source.scale)
    result["source_bone_count"] = len(source.data.bones)

    source_action = source.animation_data.action if source.animation_data and source.animation_data.action else None
    if source_action is None and bpy.data.actions:
        source_action = list(bpy.data.actions)[0]
        source.animation_data_create()
        source.animation_data.action = source_action
    if source_action is None:
        raise RuntimeError(f"No source action found in animation FBX: {animation_fbx}")
    result["source_action"] = _action_summary(source_action)

    scn.source_rig = source.name
    scn.target_rig = target.name
    scn.source_action = source_action.name
    scn.batch_retarget = False
    scn.arp_show_freeze_warn = False

    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    bpy.context.view_layer.objects.active = target

    result["build_bones_result"] = list(bpy.ops.arp.build_bones_list())

    # MIA emits Mixamo-style target bones (`mixamorig:*`). ARP's canned Mixamo
    # preset targets ARP controller names and assigns zero useful target bones
    # for these GLBs, so use explicit same-name source->target mapping.
    target_bones = {bone.name for bone in target.data.bones}
    assigned = []
    missing = []
    for item in scn.bones_map_v2:
        if item.source_bone in target_bones:
            item.name = item.source_bone
            assigned.append(item.source_bone)
        else:
            item.name = ""
            missing.append(item.source_bone)
        item.set_as_root = item.source_bone == "mixamorig:Hips"
    result["bones_map_len"] = len(scn.bones_map_v2)
    result["bones_map_assigned"] = len(assigned)
    result["bones_map_missing"] = missing
    result["retarget_poll"] = bool(bpy.ops.arp.retarget.poll())
    if not result["retarget_poll"]:
        raise RuntimeError("bpy.ops.arp.retarget.poll() returned False after configuring ARP scene state")

    start = int(source_action.frame_range[0]) if frame_start is None else int(frame_start)
    end = int(source_action.frame_range[1]) if frame_end is None or int(frame_end) <= 0 else int(frame_end)
    if end < start:
        raise ValueError(f"frame_end ({end}) must be >= frame_start ({start})")

    result["retarget_frame_start"] = start
    result["retarget_frame_end"] = end
    result["retarget_result"] = list(
        bpy.ops.arp.retarget(
            frame_start=start,
            frame_end=end,
            interpolation_type="LINEAR",
            handle_type="DEFAULT",
            only_existing_keyframes=False,
            freeze_source="NO",
            freeze_target="NO",
            show_freeze_warn=False,
            fake_user_action=True,
            clean_fk_rot=False,
            clean_ik_pole=False,
            extract_root_motion=False,
        )
    )

    target_action = target.animation_data.action if target.animation_data and target.animation_data.action else None
    if target_action is None:
        raise RuntimeError("ARP retarget finished but target armature has no action")
    result["target_action"] = _action_summary(target_action)
    result["pose_delta_left_leg"] = _pose_delta(bpy, target, target_action, "mixamorig:LeftLeg", start, end)
    result["pose_delta_left_arm"] = _pose_delta(bpy, target, target_action, "mixamorig:LeftArm", start, end)
    result["pose_delta_hips"] = _pose_delta(bpy, target, target_action, "mixamorig:Hips", start, end)

    result["removed_source_objects"] = _remove_source_objects(bpy, source)
    result["removed_actions"] = _remove_non_target_actions(bpy, target_action)
    target.animation_data_create()
    target.animation_data.action = target_action

    _select_target_for_export(bpy, target)
    bpy.ops.export_scene.gltf(filepath=str(output_glb), export_format="GLB", export_animations=True, use_selection=True)
    if not output_glb.exists():
        raise RuntimeError(f"Retarget export completed but output file was not created: {output_glb}")
    result["output_size"] = output_glb.stat().st_size

    if validate:
        # Clean in-process reimport after removing all actions/objects.
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete()
        for action in list(bpy.data.actions):
            bpy.data.actions.remove(action, do_unlink=True)
        bpy.ops.import_scene.gltf(filepath=str(output_glb))
        arms = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
        meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
        if len(arms) != 1:
            raise RuntimeError(f"Expected one armature after reimport, found {[obj.name for obj in arms]}")
        reimport_arm = arms[0]
        reimport_action = next((action for action in bpy.data.actions if "remap" in action.name), bpy.data.actions[0] if bpy.data.actions else None)
        if reimport_action is None:
            raise RuntimeError("No animation action found after reimporting exported GLB")
        result["reimport_armatures"] = [obj.name for obj in arms]
        result["reimport_meshes"] = [obj.name for obj in meshes]
        result["reimport_actions"] = [_action_summary(action) for action in bpy.data.actions]
        result["reimport_chosen_action"] = reimport_action.name
        result["reimport_armature_scale"] = list(reimport_arm.scale)
        result["reimport_bone_count"] = len(reimport_arm.data.bones)
        result["reimport_delta_left_leg"] = _pose_delta(bpy, reimport_arm, reimport_action, "mixamorig:LeftLeg", start, end)
        result["reimport_delta_left_arm"] = _pose_delta(bpy, reimport_arm, reimport_action, "mixamorig:LeftArm", start, end)
        result["reimport_delta_hips"] = _pose_delta(bpy, reimport_arm, reimport_action, "mixamorig:Hips", start, end)

    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Retarget Mixamo FBX animation onto a rigged GLB using Auto-Rig Pro")
    parser.add_argument("rigged_glb_path")
    parser.add_argument("animation_fbx_path")
    parser.add_argument("output_glb_path")
    parser.add_argument("--frame-start", type=int, default=None)
    parser.add_argument("--frame-end", type=int, default=None, help="Use <= 0 for source action end frame")
    parser.add_argument("--no-validate", action="store_true")
    parser.add_argument("--summary-json", default="")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = retarget_mixamo_to_glb(
            args.rigged_glb_path,
            args.animation_fbx_path,
            args.output_glb_path,
            frame_start=args.frame_start,
            frame_end=args.frame_end,
            validate=not args.no_validate,
        )
    except Exception as exc:  # noqa: BLE001 - CLI should emit structured failure
        result = {"error": type(exc).__name__ + ": " + str(exc), "traceback": traceback.format_exc()}
        print(json.dumps(result, indent=2, sort_keys=True), file=sys.stderr)
        return 1

    if args.summary_json:
        Path(args.summary_json).write_text(json.dumps(result, indent=2, sort_keys=True))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
