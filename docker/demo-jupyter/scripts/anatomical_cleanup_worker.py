"""Isolated anatomical skin-weight cleanup worker for rigged/animated GLBs.

The policy lives in anatomical_skinning.py; this worker only handles bpy import,
vertex-group inspection/mutation, GLB export, and validation. It must stay safe
for ComfyUI server workflows by running in a subprocess.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from collections import Counter, defaultdict
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _ensure_repo_on_path() -> None:
    repo_root = _repo_root()
    comfy_root = repo_root.parents[1]
    for path in (comfy_root, repo_root, repo_root / "nodes"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))


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


def _bbox_for_mesh(mesh_obj):
    from mathutils import Vector  # noqa: PLC0415

    corners = [mesh_obj.matrix_world @ Vector(corner) for corner in mesh_obj.bound_box]
    mins = Vector((min(p.x for p in corners), min(p.y for p in corners), min(p.z for p in corners)))
    maxs = Vector((max(p.x for p in corners), max(p.y for p in corners), max(p.z for p in corners)))
    return mins, maxs


def _vertex_world(mesh_obj, vertex):
    return mesh_obj.matrix_world @ vertex.co


def _norm_position(point, mins, maxs) -> tuple[float, float, float]:
    span_x = max(maxs.x - mins.x, 1e-8)
    span_y = max(maxs.y - mins.y, 1e-8)
    span_z = max(maxs.z - mins.z, 1e-8)
    x_norm = ((point.x - mins.x) / span_x - 0.5) * 2.0
    y_norm = ((point.y - mins.y) / span_y - 0.5) * 2.0
    z_norm = (point.z - mins.z) / span_z
    return float(x_norm), float(y_norm), float(z_norm)


def _weights_for_vertex(mesh_obj, vertex) -> dict[str, float]:
    weights: dict[str, float] = {}
    for group_ref in vertex.groups:
        if group_ref.group < len(mesh_obj.vertex_groups):
            name = mesh_obj.vertex_groups[group_ref.group].name
            weights[name] = float(group_ref.weight)
    return weights


def _dominant_name(weights: dict[str, float]) -> str:
    if not weights:
        return "<unweighted>"
    return max(weights.items(), key=lambda item: item[1])[0]


def _ensure_groups(mesh_obj, repair_weights: dict[str, float]) -> None:
    for bone_name in repair_weights:
        if mesh_obj.vertex_groups.get(bone_name) is None:
            mesh_obj.vertex_groups.new(name=bone_name)


def _apply_repair(mesh_obj, vertex_index: int, repair_weights: dict[str, float], *, mixamo_only: bool = False) -> None:
    """Replace a vertex's skinning weights with the requested anatomical weights.

    MIA/UniRig outputs may include non-Mixamo helper groups such as ``neutral_bone``.
    The old cleanup path only removed ``mixamorig:*`` groups by default, so a repaired
    head-cap vertex could keep ``neutral_bone`` at weight 1.0 while also receiving
    ``mixamorig:Head``. In viewers/export, that tie left the head cap visually pinned.
    For an explicit repair we want replacement semantics: remove every existing group
    assignment for the selected vertex, then add the normalized repair weights.
    """
    _ensure_groups(mesh_obj, repair_weights)
    for group in mesh_obj.vertex_groups:
        if not mixamo_only or group.name.startswith("mixamorig:") or group.name in repair_weights:
            try:
                group.remove([vertex_index])
            except RuntimeError:
                pass
    total = sum(max(0.0, weight) for weight in repair_weights.values()) or 1.0
    for bone_name, weight in repair_weights.items():
        mesh_obj.vertex_groups[bone_name].add([vertex_index], float(weight) / total, "REPLACE")


def _connected_components(mesh_obj) -> list[list[int]]:
    """Return vertex-index connected components based on polygon topology."""

    vertex_count = len(mesh_obj.data.vertices)
    adjacency: list[set[int]] = [set() for _ in range(vertex_count)]
    for poly in mesh_obj.data.polygons:
        verts = list(poly.vertices)
        if len(verts) < 2:
            continue
        for idx, vertex_index in enumerate(verts):
            adjacency[vertex_index].update(verts[:idx])
            adjacency[vertex_index].update(verts[idx + 1 :])
    seen = [False] * vertex_count
    components: list[list[int]] = []
    for start in range(vertex_count):
        if seen[start]:
            continue
        stack = [start]
        seen[start] = True
        comp: list[int] = []
        while stack:
            current = stack.pop()
            comp.append(current)
            for nxt in adjacency[current]:
                if not seen[nxt]:
                    seen[nxt] = True
                    stack.append(nxt)
        components.append(comp)
    return components


_MIXAMO_PARENTS = {
    "mixamorig:Hips": None,
    "mixamorig:Spine": "mixamorig:Hips",
    "mixamorig:Spine1": "mixamorig:Spine",
    "mixamorig:Spine2": "mixamorig:Spine1",
    "mixamorig:Neck": "mixamorig:Spine2",
    "mixamorig:Head": "mixamorig:Neck",
    "mixamorig:LeftShoulder": "mixamorig:Spine2",
    "mixamorig:LeftArm": "mixamorig:LeftShoulder",
    "mixamorig:LeftForeArm": "mixamorig:LeftArm",
    "mixamorig:LeftHand": "mixamorig:LeftForeArm",
    "mixamorig:LeftHandThumb1": "mixamorig:LeftHand",
    "mixamorig:LeftHandThumb2": "mixamorig:LeftHandThumb1",
    "mixamorig:LeftHandThumb3": "mixamorig:LeftHandThumb2",
    "mixamorig:LeftHandIndex1": "mixamorig:LeftHand",
    "mixamorig:LeftHandIndex2": "mixamorig:LeftHandIndex1",
    "mixamorig:LeftHandIndex3": "mixamorig:LeftHandIndex2",
    "mixamorig:LeftHandMiddle1": "mixamorig:LeftHand",
    "mixamorig:LeftHandMiddle2": "mixamorig:LeftHandMiddle1",
    "mixamorig:LeftHandMiddle3": "mixamorig:LeftHandMiddle2",
    "mixamorig:LeftHandRing1": "mixamorig:LeftHand",
    "mixamorig:LeftHandRing2": "mixamorig:LeftHandRing1",
    "mixamorig:LeftHandRing3": "mixamorig:LeftHandRing2",
    "mixamorig:LeftHandPinky1": "mixamorig:LeftHand",
    "mixamorig:LeftHandPinky2": "mixamorig:LeftHandPinky1",
    "mixamorig:LeftHandPinky3": "mixamorig:LeftHandPinky2",
    "mixamorig:RightShoulder": "mixamorig:Spine2",
    "mixamorig:RightArm": "mixamorig:RightShoulder",
    "mixamorig:RightForeArm": "mixamorig:RightArm",
    "mixamorig:RightHand": "mixamorig:RightForeArm",
    "mixamorig:RightHandThumb1": "mixamorig:RightHand",
    "mixamorig:RightHandThumb2": "mixamorig:RightHandThumb1",
    "mixamorig:RightHandThumb3": "mixamorig:RightHandThumb2",
    "mixamorig:RightHandIndex1": "mixamorig:RightHand",
    "mixamorig:RightHandIndex2": "mixamorig:RightHandIndex1",
    "mixamorig:RightHandIndex3": "mixamorig:RightHandIndex2",
    "mixamorig:RightHandMiddle1": "mixamorig:RightHand",
    "mixamorig:RightHandMiddle2": "mixamorig:RightHandMiddle1",
    "mixamorig:RightHandMiddle3": "mixamorig:RightHandMiddle2",
    "mixamorig:RightHandRing1": "mixamorig:RightHand",
    "mixamorig:RightHandRing2": "mixamorig:RightHandRing1",
    "mixamorig:RightHandRing3": "mixamorig:RightHandRing2",
    "mixamorig:RightHandPinky1": "mixamorig:RightHand",
    "mixamorig:RightHandPinky2": "mixamorig:RightHandPinky1",
    "mixamorig:RightHandPinky3": "mixamorig:RightHandPinky2",
    "mixamorig:LeftUpLeg": "mixamorig:Hips",
    "mixamorig:LeftLeg": "mixamorig:LeftUpLeg",
    "mixamorig:LeftFoot": "mixamorig:LeftLeg",
    "mixamorig:LeftToeBase": "mixamorig:LeftFoot",
    "mixamorig:RightUpLeg": "mixamorig:Hips",
    "mixamorig:RightLeg": "mixamorig:RightUpLeg",
    "mixamorig:RightFoot": "mixamorig:RightLeg",
    "mixamorig:RightToeBase": "mixamorig:RightFoot",
}


def _children_by_parent() -> dict[str, set[str]]:
    children: dict[str, set[str]] = defaultdict(set)
    for child, parent in _MIXAMO_PARENTS.items():
        if parent:
            children[parent].add(child)
    return children


def _related_bones(bone_name: str) -> set[str]:
    children = _children_by_parent()
    related = {bone_name}
    parent = _MIXAMO_PARENTS.get(bone_name)
    if parent:
        related.add(parent)
    related.update(children.get(bone_name, set()))
    short = bone_name.removeprefix("mixamorig:")
    if short.endswith("Hand"):
        side = short.removesuffix("Hand")
        related.update(name for name in _MIXAMO_PARENTS if name.startswith(f"mixamorig:{side}Hand"))
    if short.endswith("Foot"):
        side = short.removesuffix("Foot")
        related.update(name for name in _MIXAMO_PARENTS if name.startswith(f"mixamorig:{side}Toe"))
    return related


def _point_segment_distance(point, start, end) -> float:
    segment = end - start
    denom = segment.dot(segment)
    if denom <= 1e-12:
        return float((point - start).length)
    t = max(0.0, min(1.0, (point - start).dot(segment) / denom))
    nearest = start + segment * t
    return float((point - nearest).length)


def _nearest_bone_segment(point, armature) -> tuple[str | None, float | None]:
    if armature is None:
        return None, None
    best_name = None
    best_distance = None
    for bone in armature.data.bones:
        if not bone.name.startswith("mixamorig:"):
            continue
        start = armature.matrix_world @ bone.head_local
        end = armature.matrix_world @ bone.tail_local
        distance = _point_segment_distance(point, start, end)
        if best_distance is None or distance < best_distance:
            best_name = bone.name
            best_distance = distance
    return best_name, best_distance


def _bone_segment_midpoint(armature, bone_name: str):
    if armature is None or bone_name not in armature.pose.bones:
        return None
    pose_bone = armature.pose.bones[bone_name]
    return armature.matrix_world @ ((pose_bone.head + pose_bone.tail) * 0.5)


def _component_world_center(points):
    center = points[0].copy()
    center.x = sum(p.x for p in points) / len(points)
    center.y = sum(p.y for p in points) / len(points)
    center.z = sum(p.z for p in points) / len(points)
    return center


def _component_weight_totals(mesh_obj, vertex_indices: list[int]) -> defaultdict[str, float]:
    weight_totals: defaultdict[str, float] = defaultdict(float)
    for vertex_index in vertex_indices:
        for bone_name, weight in _weights_for_vertex(mesh_obj, mesh_obj.data.vertices[vertex_index]).items():
            weight_totals[bone_name] += weight
    return weight_totals


def _evaluated_vertex_world_positions(bpy, mesh_obj) -> list:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = mesh_obj.evaluated_get(depsgraph)
    return [evaluated.matrix_world @ vertex.co for vertex in evaluated.data.vertices]


def _parse_component_ids(value: str) -> set[int]:
    ids: set[int] = set()
    for part in (value or "").split(","):
        part = part.strip()
        if not part:
            continue
        ids.add(int(part))
    return ids


def _parse_repair_weights(value: str) -> dict[str, float]:
    weights: dict[str, float] = {}
    for part in (value or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"Invalid repair weight item {part!r}; expected bone=weight")
        bone_name, raw_weight = part.split("=", 1)
        bone_name = bone_name.strip()
        if not bone_name.startswith("mixamorig:"):
            bone_name = "mixamorig:" + bone_name
        weights[bone_name] = float(raw_weight)
    return weights


def _motion_component_diagnostics(
    bpy,
    mesh_obj,
    armature,
    mins,
    maxs,
    x_policy_multiplier: float,
    specs,
    *,
    frames: list[int],
    max_component_size: int,
) -> dict:
    """Find small pelvis/hip components whose motion disagrees with nearby skeleton motion."""

    from nodes.anatomical_skinning import matching_zones  # noqa: PLC0415

    if len(frames) < 2 or armature is None:
        return {"frames": frames, "candidates": [], "reason": "need_at_least_two_frames_and_armature"}

    scene = bpy.context.scene
    original_frame = scene.frame_current
    components = _connected_components(mesh_obj)
    mesh_span = max(maxs.x - mins.x, maxs.y - mins.y, maxs.z - mins.z, 1e-8)

    frame_positions: dict[int, list] = {}
    bone_midpoints: dict[int, dict[str, object]] = {}
    for frame in frames:
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        frame_positions[frame] = _evaluated_vertex_world_positions(bpy, mesh_obj)
        bone_midpoints[frame] = {
            bone.name: _bone_segment_midpoint(armature, bone.name)
            for bone in armature.data.bones
            if bone.name.startswith("mixamorig:")
        }

    start_frame = frames[0]
    end_frame = frames[-1]
    start_positions = frame_positions[start_frame]
    end_positions = frame_positions[end_frame]
    candidates = []
    for comp_index, vertex_indices in enumerate(components):
        if len(vertex_indices) > max_component_size:
            continue
        rest_points = [_vertex_world(mesh_obj, mesh_obj.data.vertices[index]) for index in vertex_indices]
        rest_center = _component_world_center(rest_points)
        x_norm, y_norm, z_norm = _norm_position(rest_center, mins, maxs)
        policy_x = x_norm * x_policy_multiplier
        zone_names = [zone.name for zone in matching_zones(policy_x, z_norm, specs)]
        # Motion diagnostics are deliberately broader than static hip zones:
        # crouched/kicking poses can push visual pelvis/upper-leg slivers outside
        # bbox hip windows or into broad hand/shoulder zones. Keep a wide torso/
        # upper-leg band and sort explicit hip-zone hits first.
        if not (0.30 <= z_norm <= 0.72 and 0.10 <= abs(policy_x) <= 0.85):
            continue
        nearest_bone, nearest_distance = _nearest_bone_segment(rest_center, armature)
        weight_totals = _component_weight_totals(mesh_obj, vertex_indices)
        sorted_weights = sorted(weight_totals.items(), key=lambda item: item[1], reverse=True)
        dominant = sorted_weights[0][0] if sorted_weights else "<unweighted>"
        start_center = _component_world_center([start_positions[index] for index in vertex_indices])
        end_center = _component_world_center([end_positions[index] for index in vertex_indices])
        component_motion = end_center - start_center
        nearest_start = bone_midpoints[start_frame].get(nearest_bone) if nearest_bone else None
        nearest_end = bone_midpoints[end_frame].get(nearest_bone) if nearest_bone else None
        nearest_motion = (nearest_end - nearest_start) if nearest_start is not None and nearest_end is not None else None
        dominant_start = bone_midpoints[start_frame].get(dominant)
        dominant_end = bone_midpoints[end_frame].get(dominant)
        dominant_motion = (dominant_end - dominant_start) if dominant_start is not None and dominant_end is not None else None
        nearest_delta_norm = None
        nearest_cosine = None
        if nearest_motion is not None:
            diff = component_motion - nearest_motion
            nearest_delta_norm = float(diff.length / mesh_span)
            denom = component_motion.length * nearest_motion.length
            if denom > 1e-10:
                nearest_cosine = float(component_motion.dot(nearest_motion) / denom)
        dominant_delta_norm = None
        if dominant_motion is not None:
            dominant_delta_norm = float((component_motion - dominant_motion).length / mesh_span)
        reasons = []
        nearest_distance_norm = (nearest_distance / mesh_span) if nearest_distance is not None else None
        if nearest_bone and dominant not in _related_bones(nearest_bone):
            reasons.append(f"nearest_bone_mismatch:{nearest_bone}:dominant:{dominant}")
        if nearest_delta_norm is not None and nearest_delta_norm > 0.030:
            reasons.append(f"motion_mismatch_nearest:{nearest_delta_norm:.3f}")
        if nearest_cosine is not None and nearest_cosine < 0.25:
            reasons.append(f"motion_direction_mismatch:{nearest_cosine:.3f}")
        if nearest_distance_norm is not None and nearest_distance_norm > 0.16:
            reasons.append(f"far_from_nearest_bone:{nearest_distance_norm:.3f}")
        if not reasons:
            continue
        candidates.append(
            {
                "component_index": comp_index,
                "vertex_count": len(vertex_indices),
                "center_norm": [x_norm, y_norm, z_norm],
                "policy_center_x_norm": policy_x,
                "zones": zone_names,
                "nearest_bone": nearest_bone,
                "nearest_bone_distance_norm": nearest_distance_norm,
                "dominant_bones": dict(sorted_weights[:8]),
                "component_motion_norm": float(component_motion.length / mesh_span),
                "nearest_motion_delta_norm": nearest_delta_norm,
                "nearest_motion_cosine": nearest_cosine,
                "dominant_motion_delta_norm": dominant_delta_norm,
                "suspect_reasons": reasons,
            }
        )
    scene.frame_set(original_frame)
    bpy.context.view_layer.update()
    candidates.sort(
        key=lambda row: (
            "right_hip" not in row["zones"],
            -(row.get("nearest_motion_delta_norm") or 0.0),
            -row["vertex_count"],
        )
    )
    return {"frames": frames, "max_component_size": max_component_size, "candidates": candidates[:200]}


def _component_diagnostics(mesh_obj, armature, mins, maxs, x_policy_multiplier: float, specs) -> dict:
    """Summarize disconnected mesh islands by topology and nearest skeleton bone."""

    from nodes.anatomical_skinning import matching_zones  # noqa: PLC0415

    components = _connected_components(mesh_obj)
    report: dict = {
        "component_count": len(components),
        "largest_components": [],
        "suspect_components": [],
    }
    component_rows = []
    for comp_index, vertex_indices in enumerate(components):
        if not vertex_indices:
            continue
        points = [_vertex_world(mesh_obj, mesh_obj.data.vertices[index]) for index in vertex_indices]
        comp_min = (min(p.x for p in points), min(p.y for p in points), min(p.z for p in points))
        comp_max = (max(p.x for p in points), max(p.y for p in points), max(p.z for p in points))
        center = (
            sum(p.x for p in points) / len(points),
            sum(p.y for p in points) / len(points),
            sum(p.z for p in points) / len(points),
        )
        center_point = points[0].copy()
        center_point.x = center[0]
        center_point.y = center[1]
        center_point.z = center[2]
        x_norm, y_norm, z_norm = _norm_position(center_point, mins, maxs)
        policy_x = x_norm * x_policy_multiplier
        nearest_bone, nearest_distance = _nearest_bone_segment(center_point, armature)
        nearest_related = _related_bones(nearest_bone) if nearest_bone else set()
        mesh_span = max(maxs.x - mins.x, maxs.y - mins.y, maxs.z - mins.z, 1e-8)
        nearest_distance_norm = (nearest_distance / mesh_span) if nearest_distance is not None else None
        weight_totals: defaultdict[str, float] = defaultdict(float)
        for vertex_index in vertex_indices:
            for bone_name, weight in _weights_for_vertex(mesh_obj, mesh_obj.data.vertices[vertex_index]).items():
                weight_totals[bone_name] += weight
        sorted_weights = sorted(weight_totals.items(), key=lambda item: item[1], reverse=True)
        dominant = sorted_weights[0][0] if sorted_weights else "<unweighted>"
        zones = matching_zones(policy_x, z_norm, specs)
        zone_names = [zone.name for zone in zones]
        reasons: list[str] = []
        if nearest_bone and dominant not in nearest_related:
            reasons.append(f"nearest_bone_mismatch:{nearest_bone}:dominant:{dominant}")
        if nearest_distance_norm is not None and nearest_distance_norm > 0.18:
            reasons.append(f"far_from_skeleton:{nearest_distance_norm:.3f}")
        row = {
            "component_index": comp_index,
            "vertex_count": len(vertex_indices),
            "center_norm": [x_norm, y_norm, z_norm],
            "policy_center_x_norm": policy_x,
            "bbox_min": list(comp_min),
            "bbox_max": list(comp_max),
            "zones": zone_names,
            "nearest_bone": nearest_bone,
            "nearest_bone_distance_norm": nearest_distance_norm,
            "nearest_related_bones": sorted(nearest_related),
            "dominant_bones": dict(sorted_weights[:8]),
            "suspect_reasons": reasons,
        }
        component_rows.append(row)
        if reasons:
            report["suspect_components"].append(row)
    report["largest_components"] = sorted(component_rows, key=lambda row: row["vertex_count"], reverse=True)[:12]
    report["suspect_components"] = sorted(
        report["suspect_components"],
        key=lambda row: (row["zones"] == [], -row["vertex_count"]),
    )[:80]
    return report


def _mesh_armature(mesh_obj):
    for mod in mesh_obj.modifiers:
        if mod.type == "ARMATURE" and mod.object is not None:
            return mod.object
    return mesh_obj.find_armature()


def _infer_x_policy_multiplier(mesh_obj, mins, maxs) -> tuple[float, dict]:
    """Infer whether positive normalized X is anatomical right or left.

    The pure policy uses x>0 as right. Blender/glTF imports can mirror visible
    handedness, so infer from existing dominant Left*/Right* weights. Return -1
    when coordinates should be flipped before zone matching.
    """

    left_x: list[float] = []
    right_x: list[float] = []
    for vertex in mesh_obj.data.vertices:
        weights = _weights_for_vertex(mesh_obj, vertex)
        dominant = _dominant_name(weights)
        if not dominant.startswith("mixamorig:"):
            continue
        point = _vertex_world(mesh_obj, vertex)
        x_norm, _y_norm, _z_norm = _norm_position(point, mins, maxs)
        short = dominant.removeprefix("mixamorig:")
        if short.startswith("Left"):
            left_x.append(x_norm)
        elif short.startswith("Right"):
            right_x.append(x_norm)
    left_avg = sum(left_x) / len(left_x) if left_x else 0.0
    right_avg = sum(right_x) / len(right_x) if right_x else 0.0
    # If left-weighted vertices are on positive X and right-weighted vertices on
    # negative X, flip coordinates for the policy's side tests.
    multiplier = -1.0 if left_avg > right_avg else 1.0
    return multiplier, {
        "left_weighted_vertex_count": len(left_x),
        "right_weighted_vertex_count": len(right_x),
        "left_weighted_avg_x_norm": left_avg,
        "right_weighted_avg_x_norm": right_avg,
        "x_policy_multiplier": multiplier,
    }


def _select_export_objects(bpy, armatures, meshes) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    for obj in [*armatures, *meshes]:
        obj.select_set(True)
    if armatures:
        bpy.context.view_layer.objects.active = armatures[0]
    elif meshes:
        bpy.context.view_layer.objects.active = meshes[0]


def _validate_reimport(bpy, output_glb: Path) -> dict:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action, do_unlink=True)
    bpy.ops.import_scene.gltf(filepath=str(output_glb), disable_bone_shape=True)
    arms = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    actions = list(bpy.data.actions)
    return {
        "armatures": [{"name": obj.name, "bones": len(obj.data.bones), "scale": list(obj.scale)} for obj in arms],
        "meshes": [
            {
                "name": obj.name,
                "vertices": len(obj.data.vertices),
                "vertex_groups": len(obj.vertex_groups),
                "modifiers": [mod.type for mod in obj.modifiers],
                "materials": [slot.material.name if slot.material else None for slot in obj.material_slots],
                "uv_layers": [uv.name for uv in obj.data.uv_layers],
            }
            for obj in meshes
        ],
        "actions": [_action_summary(action) for action in actions],
    }


def cleanup_glb(
    input_glb_path: str,
    output_glb_path: str,
    *,
    mode: str = "conservative",
    max_fraction_per_zone: float = 0.03,
    repair_zones: set[str] | None = None,
    motion_frames: list[int] | None = None,
    max_motion_component_size: int = 64,
    component_repair_ids: set[int] | None = None,
    component_repair_weights: dict[str, float] | None = None,
    validate: bool = True,
) -> dict:
    _ensure_repo_on_path()
    import bpy  # noqa: PLC0415
    from nodes.anatomical_skinning import default_zone_specs, repair_plan_for_vertex  # noqa: PLC0415

    input_glb = Path(input_glb_path)
    output_glb = Path(output_glb_path)
    if not input_glb.exists():
        raise FileNotFoundError(f"Input GLB not found: {input_glb}")
    output_glb.parent.mkdir(parents=True, exist_ok=True)
    if mode not in {"diagnostic", "conservative", "motion-diagnostic", "component-repair"}:
        raise ValueError(f"Unsupported cleanup mode: {mode}")
    active_repair_zones = repair_zones or {"head_top", "head_neck", "left_hip", "right_hip"}

    result: dict = {
        "input_glb_path": str(input_glb),
        "output_glb_path": str(output_glb),
        "mode": mode,
        "max_fraction_per_zone": max_fraction_per_zone,
        "active_repair_zones": sorted(active_repair_zones),
        "motion_frames": motion_frames or [0, 16, 24, 32],
        "max_motion_component_size": max_motion_component_size,
        "component_repair_ids": sorted(component_repair_ids or []),
        "component_repair_weights": component_repair_weights or {},
    }
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    import_result = bpy.ops.import_scene.gltf(filepath=str(input_glb), disable_bone_shape=True)
    result["import_result"] = list(import_result)

    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    actions = list(bpy.data.actions)
    result["source"] = {
        "armatures": [{"name": obj.name, "bones": len(obj.data.bones), "scale": list(obj.scale)} for obj in armatures],
        "meshes": [{"name": obj.name, "vertices": len(obj.data.vertices), "vertex_groups": len(obj.vertex_groups)} for obj in meshes],
        "actions": [_action_summary(action) for action in actions],
    }

    specs = default_zone_specs()
    zone_candidates: Counter[str] = Counter()
    zone_suspicious: Counter[str] = Counter()
    zone_changed: Counter[str] = Counter()
    dominant_before: dict[str, Counter[str]] = defaultdict(Counter)
    dominant_after: dict[str, Counter[str]] = defaultdict(Counter)
    mesh_reports = []
    component_changed = 0

    for mesh_obj in meshes:
        armature = _mesh_armature(mesh_obj)
        mins, maxs = _bbox_for_mesh(mesh_obj)
        x_policy_multiplier, orientation_report = _infer_x_policy_multiplier(mesh_obj, mins, maxs)
        components = _connected_components(mesh_obj)
        zone_limits = {spec.name: max(1, int(len(mesh_obj.data.vertices) * max_fraction_per_zone)) for spec in specs}
        mesh_report = {
            "mesh": mesh_obj.name,
            "armature": armature.name if armature else None,
            "vertices": len(mesh_obj.data.vertices),
            "bbox_min": list(mins),
            "bbox_max": list(maxs),
            "orientation": orientation_report,
            "components": _component_diagnostics(mesh_obj, armature, mins, maxs, x_policy_multiplier, specs),
        }
        if mode == "motion-diagnostic":
            mesh_report["motion_components"] = _motion_component_diagnostics(
                bpy,
                mesh_obj,
                armature,
                mins,
                maxs,
                x_policy_multiplier,
                specs,
                frames=motion_frames or [0, 16, 24, 32],
                max_component_size=max_motion_component_size,
            )
        if mode == "component-repair":
            repair_ids = component_repair_ids or set()
            repair_weights = component_repair_weights or {"mixamorig:RightUpLeg": 0.62, "mixamorig:Hips": 0.38}
            mesh_report["component_repair"] = {"ids": sorted(repair_ids), "weights": repair_weights, "changed_vertices": 0}
            for comp_index, vertex_indices in enumerate(components):
                if comp_index not in repair_ids:
                    continue
                for vertex_index in vertex_indices:
                    _apply_repair(mesh_obj, vertex_index, repair_weights)
                    component_changed += 1
                    mesh_report["component_repair"]["changed_vertices"] += 1
        for vertex in mesh_obj.data.vertices:
            point = _vertex_world(mesh_obj, vertex)
            x_norm, _y_norm, z_norm = _norm_position(point, mins, maxs)
            weights = _weights_for_vertex(mesh_obj, vertex)
            plan = repair_plan_for_vertex(x_norm * x_policy_multiplier, z_norm, weights, specs)
            if plan is None:
                continue
            spec, repair_weights = plan
            zone_candidates[spec.name] += 1
            zone_suspicious[spec.name] += 1
            dominant_before[spec.name][_dominant_name(weights)] += 1
            if mode == "conservative" and spec.name in active_repair_zones and zone_changed[spec.name] < zone_limits[spec.name]:
                _apply_repair(mesh_obj, vertex.index, repair_weights)
                zone_changed[spec.name] += 1
                after_weights = _weights_for_vertex(mesh_obj, vertex)
                dominant_after[spec.name][_dominant_name(after_weights)] += 1
        mesh_reports.append(mesh_report)

    result["meshes"] = mesh_reports
    result["zones"] = {
        spec.name: {
            "candidate_vertices": int(zone_candidates[spec.name]),
            "suspicious_vertices": int(zone_suspicious[spec.name]),
            "changed_vertices": int(zone_changed[spec.name]),
            "dominant_bones_before": dict(dominant_before[spec.name].most_common(12)),
            "dominant_bones_after": dict(dominant_after[spec.name].most_common(12)),
            "allowed_bones": list(spec.allowed_bones),
            "repair_weights": dict(spec.repair_weights),
        }
        for spec in specs
        if zone_candidates[spec.name] or zone_changed[spec.name]
    }
    result["total_changed_vertices"] = int(sum(zone_changed.values()))
    result["component_changed_vertices"] = int(component_changed)

    # Preserve the active action if one exists before export.
    if armatures and actions:
        armatures[0].animation_data_create()
        armatures[0].animation_data.action = actions[0]
    _select_export_objects(bpy, armatures, meshes)
    export_result = bpy.ops.export_scene.gltf(
        filepath=str(output_glb),
        export_format="GLB",
        export_animations=True,
        use_selection=True,
    )
    result["export_result"] = list(export_result)
    result["output_size"] = output_glb.stat().st_size if output_glb.exists() else 0
    if not output_glb.exists():
        raise RuntimeError(f"Cleanup export completed but output GLB was not created: {output_glb}")
    if validate:
        result["reimport"] = _validate_reimport(bpy, output_glb)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Conservative anatomical skin-weight cleanup for rigged GLBs")
    parser.add_argument("input_glb_path")
    parser.add_argument("output_glb_path")
    parser.add_argument("--mode", choices=["diagnostic", "conservative", "motion-diagnostic", "component-repair"], default="conservative")
    parser.add_argument("--max-fraction-per-zone", type=float, default=0.03)
    parser.add_argument("--repair-zones", default="head_top,head_neck,left_hip,right_hip", help="Comma-separated zones allowed to be rewritten in conservative mode. Diagnostics still cover all zones.")
    parser.add_argument("--motion-frames", default="0,16,24,32", help="Comma-separated animation frames for motion diagnostics.")
    parser.add_argument("--max-motion-component-size", type=int, default=64)
    parser.add_argument("--component-repair-ids", default="", help="Comma-separated connected-component ids to rewrite in component-repair mode.")
    parser.add_argument("--component-repair-weights", default="RightUpLeg=0.62,Hips=0.38", help="Comma-separated bone=weight list for component-repair mode.")
    parser.add_argument("--no-validate", action="store_true")
    parser.add_argument("--summary-json", default="")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = cleanup_glb(
            args.input_glb_path,
            args.output_glb_path,
            mode=args.mode,
            max_fraction_per_zone=args.max_fraction_per_zone,
            repair_zones={zone.strip() for zone in args.repair_zones.split(",") if zone.strip()},
            motion_frames=[int(frame.strip()) for frame in args.motion_frames.split(",") if frame.strip()],
            max_motion_component_size=args.max_motion_component_size,
            component_repair_ids=_parse_component_ids(args.component_repair_ids),
            component_repair_weights=_parse_repair_weights(args.component_repair_weights),
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
