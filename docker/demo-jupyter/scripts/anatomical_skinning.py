"""Conservative anatomical skin-weight cleanup helpers.

This module is intentionally pure Python so the zone/weighting policy can be
unit-tested without importing bpy. The bpy worker applies the returned plans to
Blender vertex groups.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


MIXAMO = "mixamorig:"


@dataclass(frozen=True)
class ZoneSpec:
    """A conservative body-zone definition in normalized mesh-bbox space."""

    name: str
    allowed_bones: tuple[str, ...]
    repair_weights: tuple[tuple[str, float], ...]
    min_z: float = 0.0
    max_z: float = 1.0
    min_abs_x: float = 0.0
    max_abs_x: float = 1.0
    side: str = "any"  # any, left, right, center
    min_allowed_weight: float = 0.35


def mixamo_bone(name: str) -> str:
    return name if name.startswith(MIXAMO) else f"{MIXAMO}{name}"


def _side_matches(x_norm: float, side: str) -> bool:
    if side == "any":
        return True
    if side == "center":
        return abs(x_norm) <= 0.32
    # Blender/Mixamo coordinate handedness can vary after import/export. The
    # cleanup framework therefore exposes explicit left/right zones but treats
    # their sign convention as a policy detail. Current MIA smokes use x<0 for
    # visually left and x>0 for visually right in front view.
    if side == "left":
        return x_norm < -0.18
    if side == "right":
        return x_norm > 0.18
    return False


def default_zone_specs() -> tuple[ZoneSpec, ...]:
    """Return high-confidence humanoid zones for conservative repair.

    These are deliberately broad diagnostics but conservative repair targets.
    The worker only rewrites vertices whose current dominant/combined weights are
    anatomically suspicious for their zone.
    """

    return (
        ZoneSpec(
            name="head_top",
            min_z=0.90,
            max_z=1.01,
            max_abs_x=0.45,
            side="center",
            allowed_bones=(mixamo_bone("Head"), mixamo_bone("Neck")),
            repair_weights=((mixamo_bone("Head"), 1.0),),
            min_allowed_weight=0.75,
        ),
        ZoneSpec(
            name="head_neck",
            min_z=0.78,
            max_z=0.93,
            max_abs_x=0.42,
            side="center",
            allowed_bones=(mixamo_bone("Head"), mixamo_bone("Neck"), mixamo_bone("Spine2")),
            repair_weights=((mixamo_bone("Head"), 0.82), (mixamo_bone("Neck"), 0.18)),
            min_allowed_weight=0.55,
        ),
        ZoneSpec(
            name="right_hip",
            min_z=0.38,
            max_z=0.62,
            min_abs_x=0.12,
            max_abs_x=0.50,
            side="right",
            allowed_bones=(mixamo_bone("Hips"), mixamo_bone("RightUpLeg"), mixamo_bone("RightLeg"), mixamo_bone("Spine"), mixamo_bone("Spine1")),
            repair_weights=((mixamo_bone("RightUpLeg"), 0.62), (mixamo_bone("Hips"), 0.38)),
            min_allowed_weight=0.45,
        ),
        ZoneSpec(
            name="left_hip",
            min_z=0.38,
            max_z=0.62,
            min_abs_x=0.12,
            max_abs_x=0.50,
            side="left",
            allowed_bones=(mixamo_bone("Hips"), mixamo_bone("LeftUpLeg"), mixamo_bone("LeftLeg"), mixamo_bone("Spine"), mixamo_bone("Spine1")),
            repair_weights=((mixamo_bone("LeftUpLeg"), 0.62), (mixamo_bone("Hips"), 0.38)),
            min_allowed_weight=0.45,
        ),
        ZoneSpec(
            name="right_shoulder",
            min_z=0.62,
            max_z=0.82,
            min_abs_x=0.30,
            max_abs_x=0.72,
            side="right",
            allowed_bones=(mixamo_bone("RightShoulder"), mixamo_bone("RightArm"), mixamo_bone("Spine2"), mixamo_bone("Neck")),
            repair_weights=((mixamo_bone("RightShoulder"), 0.55), (mixamo_bone("RightArm"), 0.45)),
            min_allowed_weight=0.45,
        ),
        ZoneSpec(
            name="left_shoulder",
            min_z=0.62,
            max_z=0.82,
            min_abs_x=0.30,
            max_abs_x=0.72,
            side="left",
            allowed_bones=(mixamo_bone("LeftShoulder"), mixamo_bone("LeftArm"), mixamo_bone("Spine2"), mixamo_bone("Neck")),
            repair_weights=((mixamo_bone("LeftShoulder"), 0.55), (mixamo_bone("LeftArm"), 0.45)),
            min_allowed_weight=0.45,
        ),
        ZoneSpec(
            name="right_hand",
            min_z=0.22,
            max_z=0.72,
            min_abs_x=0.58,
            side="right",
            allowed_bones=(mixamo_bone("RightHand"), mixamo_bone("RightForeArm"), mixamo_bone("RightArm")),
            repair_weights=((mixamo_bone("RightHand"), 0.70), (mixamo_bone("RightForeArm"), 0.30)),
            min_allowed_weight=0.50,
        ),
        ZoneSpec(
            name="left_hand",
            min_z=0.22,
            max_z=0.72,
            min_abs_x=0.58,
            side="left",
            allowed_bones=(mixamo_bone("LeftHand"), mixamo_bone("LeftForeArm"), mixamo_bone("LeftArm")),
            repair_weights=((mixamo_bone("LeftHand"), 0.70), (mixamo_bone("LeftForeArm"), 0.30)),
            min_allowed_weight=0.50,
        ),
        ZoneSpec(
            name="right_foot",
            min_z=-0.01,
            max_z=0.18,
            min_abs_x=0.08,
            side="right",
            allowed_bones=(mixamo_bone("RightFoot"), mixamo_bone("RightToeBase"), mixamo_bone("RightLeg")),
            repair_weights=((mixamo_bone("RightFoot"), 0.82), (mixamo_bone("RightToeBase"), 0.18)),
            min_allowed_weight=0.55,
        ),
        ZoneSpec(
            name="left_foot",
            min_z=-0.01,
            max_z=0.18,
            min_abs_x=0.08,
            side="left",
            allowed_bones=(mixamo_bone("LeftFoot"), mixamo_bone("LeftToeBase"), mixamo_bone("LeftLeg")),
            repair_weights=((mixamo_bone("LeftFoot"), 0.82), (mixamo_bone("LeftToeBase"), 0.18)),
            min_allowed_weight=0.55,
        ),
    )


def matching_zones(x_norm: float, z_norm: float, specs: Iterable[ZoneSpec] | None = None) -> list[ZoneSpec]:
    """Return zone specs matching a normalized x/z location.

    x_norm is centered around 0 with approximately [-1, 1] range. z_norm is
    bbox-normalized [0, 1].
    """

    matches: list[ZoneSpec] = []
    for spec in specs or default_zone_specs():
        if z_norm < spec.min_z or z_norm > spec.max_z:
            continue
        if abs(x_norm) < spec.min_abs_x or abs(x_norm) > spec.max_abs_x:
            continue
        if not _side_matches(x_norm, spec.side):
            continue
        matches.append(spec)
    return matches


def dominant_weight(weights: dict[str, float]) -> tuple[str | None, float]:
    if not weights:
        return None, 0.0
    bone, weight = max(weights.items(), key=lambda item: item[1])
    return bone, float(weight)


def allowed_weight_sum(weights: dict[str, float], allowed_bones: Iterable[str]) -> float:
    allowed = set(allowed_bones)
    return float(sum(weight for bone, weight in weights.items() if bone in allowed))


def is_suspicious_for_zone(weights: dict[str, float], spec: ZoneSpec) -> bool:
    """Return True if current weights are high-confidence anatomically suspicious."""

    dominant, _ = dominant_weight(weights)
    allowed_sum = allowed_weight_sum(weights, spec.allowed_bones)
    if dominant is None:
        return True
    if dominant not in spec.allowed_bones:
        return True
    return allowed_sum < spec.min_allowed_weight


def repair_plan_for_vertex(
    x_norm: float,
    z_norm: float,
    weights: dict[str, float],
    specs: Iterable[ZoneSpec] | None = None,
) -> tuple[ZoneSpec, dict[str, float]] | None:
    """Return the first high-confidence zone repair plan for a vertex, if any."""

    for spec in matching_zones(x_norm, z_norm, specs):
        if is_suspicious_for_zone(weights, spec):
            return spec, dict(spec.repair_weights)
    return None
