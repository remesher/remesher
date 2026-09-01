"""Re-skin a rigged GLB with Blender automatic weights in an isolated bpy process."""

from __future__ import annotations

import argparse
import ctypes
import errno
import json
import math
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

try:
    import bpy
except ModuleNotFoundError:  # Pure helpers are unit-tested without Blender installed.
    bpy = None


def _new_temp_glb_path(output_glb: Path, purpose: str) -> Path:
    """Create a private same-filesystem workspace for a Blender GLB export."""
    workspace = Path(tempfile.mkdtemp(
        prefix=f".{output_glb.stem}.{purpose}-",
        dir=output_glb.parent,
    ))
    workspace.chmod(0o700)
    return workspace / f"{purpose}.glb"


def _remove_temp_glb_path(path: Path) -> None:
    path.unlink(missing_ok=True)
    shutil.rmtree(path.parent, ignore_errors=True)


def _validate_weld_distance(value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError("weld_distance must be finite and greater than 0")


def _matrix_max_abs_delta(first, second) -> float:
    return max(
        abs(first[row][column] - second[row][column])
        for row in range(4)
        for column in range(4)
    )


def _promote_file_noreplace(source: Path, destination: Path) -> None:
    """Atomically rename a file without replacing an existing destination."""
    if sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise OSError(
                errno.ENOTSUP,
                "libc does not expose renameat2(RENAME_NOREPLACE)",
                str(destination),
            )
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        result = renameat2(
            -100,
            os.fsencode(source),
            -100,
            os.fsencode(destination),
            1,
        )
        if result != 0:
            error_number = ctypes.get_errno()
            raise OSError(
                error_number,
                os.strerror(error_number),
                str(destination),
            )
        return
    if os.name == "nt":
        os.rename(source, destination)
        return
    raise OSError(
        errno.ENOTSUP,
        "Atomic no-replace rename is unsupported on this platform",
        str(destination),
    )


def _write_json_noreplace(path: Path, value: dict) -> None:
    """Create structured output exclusively; never truncate an existing file."""
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)


def _deform_group_indices(mesh, armature) -> set[int]:
    deform_names = {bone.name for bone in armature.data.bones if bone.use_deform}
    return {
        group.index for group in mesh.vertex_groups if group.name in deform_names
    }


def _vertex_has_positive_deform_weight(vertex, deform_group_indices: set[int]) -> bool:
    return any(
        assignment.group in deform_group_indices and assignment.weight > 0
        for assignment in vertex.groups
    )


def _count_positive_deform_weights(mesh, armature) -> int:
    deform_group_indices = _deform_group_indices(mesh, armature)
    return sum(
        _vertex_has_positive_deform_weight(vertex, deform_group_indices)
        for vertex in mesh.data.vertices
    )


def _segment_distance(point, start, end) -> float:
    delta = end - start
    if delta.length_squared == 0:
        return (point - start).length
    t = max(0.0, min(1.0, (point - start).dot(delta) / delta.length_squared))
    return (point - (start + t * delta)).length


def _fill_unweighted_from_nearest_bone(mesh, armature) -> int:
    bones = [bone for bone in armature.data.bones if bone.use_deform]
    segments = {
        bone.name: (
            armature.matrix_world @ bone.head_local,
            armature.matrix_world @ bone.tail_local,
        )
        for bone in bones
    }
    groups = {
        bone.name: mesh.vertex_groups.get(bone.name)
        or mesh.vertex_groups.new(name=bone.name)
        for bone in bones
    }
    deform_group_indices = _deform_group_indices(mesh, armature)
    filled = 0
    for vertex in mesh.data.vertices:
        if _vertex_has_positive_deform_weight(vertex, deform_group_indices):
            continue
        point = mesh.matrix_world @ vertex.co
        nearest = min(
            segments,
            key=lambda name: _segment_distance(point, *segments[name]),
        )
        groups[nearest].add([vertex.index], 1.0, "REPLACE")
        filled += 1
    return filled


def _small_component_vertices_to_remove(
    components: dict[int, list[int]], max_component_vertices: int
) -> list[int]:
    if len(components) <= 1:
        return []
    largest_root = max(components, key=lambda root: len(components[root]))
    return [
        index
        for root, component in components.items()
        if root != largest_root and len(component) <= max_component_vertices
        for index in component
    ]


def _removed_component_count(
    components: dict[int, list[int]], removed_vertices: list[int]
) -> int:
    removed = set(removed_vertices)
    return sum(
        bool(component) and component[0] in removed
        for component in components.values()
    )


def _remove_small_disconnected_components(
    mesh,
    *,
    max_component_vertices: int = 128,
    max_removed_fraction: float = 0.005,
) -> dict:
    if bpy is None:
        raise RuntimeError("Blender bpy is required for mesh cleanup")
    vertex_count = len(mesh.data.vertices)
    parent = list(range(vertex_count))
    sizes = [1] * vertex_count

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(a: int, b: int) -> None:
        root_a, root_b = find(a), find(b)
        if root_a == root_b:
            return
        if sizes[root_a] < sizes[root_b]:
            root_a, root_b = root_b, root_a
        parent[root_b] = root_a
        sizes[root_a] += sizes[root_b]

    for edge in mesh.data.edges:
        union(*edge.vertices)
    components: dict[int, list[int]] = {}
    for index in range(vertex_count):
        components.setdefault(find(index), []).append(index)
    remove = _small_component_vertices_to_remove(
        components, max_component_vertices
    )
    removed_fraction = len(remove) / vertex_count if vertex_count else 1.0
    if removed_fraction > max_removed_fraction:
        raise RuntimeError(
            "Disconnected-island cleanup would remove too much geometry: "
            f"{len(remove)}/{vertex_count} "
            f"({removed_fraction:.6f} > {max_removed_fraction:.6f})"
        )
    if remove:
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.object.mode_set(mode="OBJECT")
        for index in remove:
            mesh.data.vertices[index].select = True
        mesh.data.update()
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.delete(type="VERT")
        bpy.ops.object.mode_set(mode="OBJECT")
    component_sizes = sorted((len(component) for component in components.values()), reverse=True)
    return {
        "component_count": len(components),
        "largest_component_vertices": component_sizes[0] if component_sizes else 0,
        "small_components_removed": _removed_component_count(
            components, remove
        ),
        "vertices_removed": len(remove),
        "removed_fraction": removed_fraction,
        "max_component_vertices": max_component_vertices,
        "max_removed_fraction": max_removed_fraction,
    }


def _export_validate_and_promote(
    output_glb: Path,
    mesh,
    armature,
    *,
    expected_material_count: int,
    expected_image_count: int,
    expected_uv_layer_count: int,
    expected_bone_count: int,
) -> tuple[list[str], int, dict]:
    """Export to a unique candidate, validate it, then atomically promote it."""
    if bpy is None:
        raise RuntimeError("Blender bpy is required for GLB export validation")
    candidate_glb = _new_temp_glb_path(output_glb, "candidate")
    try:
        bpy.ops.object.select_all(action="DESELECT")
        armature.select_set(True)
        mesh.select_set(True)
        bpy.context.view_layer.objects.active = armature
        export_result = bpy.ops.export_scene.gltf(
            filepath=str(candidate_glb),
            export_format="GLB",
            export_animations=False,
            use_selection=True,
        )
        if not candidate_glb.exists() or candidate_glb.stat().st_size == 0:
            raise RuntimeError(
                "Automatic-weight GLB export did not create a non-empty candidate"
            )
        output_size = candidate_glb.stat().st_size

        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(
            filepath=str(candidate_glb),
            disable_bone_shape=True,
        )
        reimport_armatures = [
            obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"
        ]
        reimport_meshes = [
            obj for obj in bpy.context.scene.objects if obj.type == "MESH"
        ]
        if len(reimport_armatures) != 1 or len(reimport_meshes) != 1:
            raise RuntimeError(
                "Automatic-weight GLB reimport contract failed: "
                f"armatures={len(reimport_armatures)}, meshes={len(reimport_meshes)}"
            )
        reimport_armature = reimport_armatures[0]
        reimport_mesh = reimport_meshes[0]
        reimport_modifiers = [
            modifier
            for modifier in reimport_mesh.modifiers
            if modifier.type == "ARMATURE"
        ]
        if not reimport_modifiers or not any(
            modifier.object == reimport_armature for modifier in reimport_modifiers
        ):
            raise RuntimeError(
                "Automatic-weight GLB reimport armature modifier does not target "
                "the reimported armature"
            )
        if len(reimport_armature.data.bones) != expected_bone_count:
            raise RuntimeError(
                "Automatic-weight GLB reimport changed bone count: "
                f"{len(reimport_armature.data.bones)} != {expected_bone_count}"
            )
        if len(reimport_mesh.data.materials) < expected_material_count:
            raise RuntimeError("Automatic-weight GLB reimport lost materials")
        if len(bpy.data.images) < expected_image_count:
            raise RuntimeError("Automatic-weight GLB reimport lost embedded images")
        if len(reimport_mesh.data.uv_layers) < expected_uv_layer_count:
            raise RuntimeError("Automatic-weight GLB reimport lost UV layers")
        reimport_weighted_vertices = _count_positive_deform_weights(
            reimport_mesh, reimport_armature
        )
        if reimport_weighted_vertices != len(reimport_mesh.data.vertices):
            raise RuntimeError(
                "Automatic-weight GLB reimport has vertices without positive deform "
                f"weights: {reimport_weighted_vertices}/{len(reimport_mesh.data.vertices)}"
            )

        reimport = {
            "armatures": [obj.name for obj in reimport_armatures],
            "bones": len(reimport_armature.data.bones),
            "meshes": [obj.name for obj in reimport_meshes],
            "materials": [
                material.name for material in reimport_mesh.data.materials
            ],
            "images": [image.name for image in bpy.data.images],
            "uv_layers": [layer.name for layer in reimport_mesh.data.uv_layers],
            "armature_modifiers": [
                modifier.name for modifier in reimport_modifiers
            ],
            "positive_deform_weighted_vertices": reimport_weighted_vertices,
        }
        _promote_file_noreplace(candidate_glb, output_glb)
        return list(export_result), output_size, reimport
    finally:
        _remove_temp_glb_path(candidate_glb)


def auto_skin_glb(
    input_glb_path: str,
    output_glb_path: str,
    *,
    weld_distance: float = 1e-6,
    max_unweighted_fraction: float = 0.005,
) -> dict:
    if bpy is None:
        raise RuntimeError("Blender bpy is required for automatic skinning")
    input_glb = Path(input_glb_path)
    output_glb = Path(output_glb_path)
    if not input_glb.exists() or not input_glb.is_file():
        raise FileNotFoundError(f"Input GLB not found: {input_glb}")
    _validate_weld_distance(weld_distance)
    if not 0 <= max_unweighted_fraction <= 1:
        raise ValueError("max_unweighted_fraction must be between 0 and 1")
    output_glb.parent.mkdir(parents=True, exist_ok=True)
    if output_glb.exists():
        raise FileExistsError(f"Refusing to overwrite existing output GLB: {output_glb}")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    import_result = bpy.ops.import_scene.gltf(
        filepath=str(input_glb),
        disable_bone_shape=True,
    )
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if len(armatures) != 1 or len(meshes) != 1:
        raise RuntimeError(
            "Automatic weighting requires exactly one armature and one mesh; "
            f"found armatures={[obj.name for obj in armatures]}, "
            f"meshes={[obj.name for obj in meshes]}"
        )
    armature = armatures[0]
    mesh = meshes[0]
    armature.data.pose_position = "REST"
    bpy.context.view_layer.update()
    source_materials = [material.name for material in mesh.data.materials]
    source_images = [image.name for image in bpy.data.images]
    source_uv_layers = [layer.name for layer in mesh.data.uv_layers]
    source_bone_count = len(armature.data.bones)

    # Normalize MIA's raw exporter output through a clean Blender GLB round-trip.
    # The raw triangle-duplicated mesh can make bone heat fail even after welding;
    # the normalized representation is the path proven by cleanup-worker outputs.
    normalized_glb = _new_temp_glb_path(output_glb, "normalized")
    try:
        bpy.ops.object.select_all(action="DESELECT")
        armature.select_set(True)
        mesh.select_set(True)
        bpy.context.view_layer.objects.active = armature
        normalize_export_result = bpy.ops.export_scene.gltf(
            filepath=str(normalized_glb),
            export_format="GLB",
            export_animations=False,
            use_selection=True,
        )
        bpy.ops.wm.read_factory_settings(use_empty=True)
        normalize_import_result = bpy.ops.import_scene.gltf(
            filepath=str(normalized_glb),
            disable_bone_shape=True,
        )
    finally:
        _remove_temp_glb_path(normalized_glb)
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if len(armatures) != 1 or len(meshes) != 1:
        raise RuntimeError(
            "Normalized MIA GLB requires exactly one armature and one mesh; "
            f"found armatures={[obj.name for obj in armatures]}, "
            f"meshes={[obj.name for obj in meshes]}"
        )
    armature = armatures[0]
    mesh = meshes[0]
    armature.data.pose_position = "REST"
    bpy.context.view_layer.update()

    normalized_materials = [material.name for material in mesh.data.materials]
    normalized_images = [image.name for image in bpy.data.images]
    normalized_uv_layers = [layer.name for layer in mesh.data.uv_layers]
    if len(normalized_materials) < len(source_materials):
        raise RuntimeError("Normalized MIA GLB lost materials")
    if len(normalized_images) < len(source_images):
        raise RuntimeError("Normalized MIA GLB lost embedded images")
    if len(normalized_uv_layers) < len(source_uv_layers):
        raise RuntimeError("Normalized MIA GLB lost UV layers")
    if len(armature.data.bones) != source_bone_count:
        raise RuntimeError(
            "Normalized MIA GLB changed bone count: "
            f"{len(armature.data.bones)} != {source_bone_count}"
        )
    old_vertex_groups = [group.name for group in mesh.vertex_groups]
    old_armature_modifiers = [
        modifier.name for modifier in mesh.modifiers if modifier.type == "ARMATURE"
    ]

    bpy.ops.object.select_all(action="DESELECT")
    mesh.select_set(True)
    bpy.context.view_layer.objects.active = mesh
    vertices_before_weld = len(mesh.data.vertices)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    weld_result = bpy.ops.mesh.remove_doubles(threshold=weld_distance)
    bpy.ops.object.mode_set(mode="OBJECT")
    vertices_after_weld = len(mesh.data.vertices)
    island_cleanup = _remove_small_disconnected_components(mesh)

    world_matrix = mesh.matrix_world.copy()
    mesh.parent = None
    mesh.matrix_world = world_matrix
    for modifier in list(mesh.modifiers):
        if modifier.type == "ARMATURE":
            mesh.modifiers.remove(modifier)
    for group in list(mesh.vertex_groups):
        mesh.vertex_groups.remove(group)

    bpy.ops.object.select_all(action="DESELECT")
    mesh.select_set(True)
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    parent_result = bpy.ops.object.parent_set(
        type="ARMATURE_AUTO", keep_transform=True
    )
    bpy.context.view_layer.update()
    parent_world_matrix_delta = _matrix_max_abs_delta(
        world_matrix, mesh.matrix_world
    )
    if parent_world_matrix_delta > 1e-6:
        raise RuntimeError(
            "Automatic weighting changed mesh world transform during parenting: "
            f"max_delta={parent_world_matrix_delta}"
        )

    weighted_vertices = _count_positive_deform_weights(mesh, armature)
    unweighted_vertices = len(mesh.data.vertices) - weighted_vertices
    unweighted_fraction = (
        unweighted_vertices / len(mesh.data.vertices) if mesh.data.vertices else 1.0
    )
    automatic_heat_parent_result = list(parent_result)
    automatic_heat_weighted_vertices = weighted_vertices
    automatic_heat_unweighted_vertices = unweighted_vertices
    if weighted_vertices == 0:
        raise RuntimeError(
            "Blender automatic heat weighting assigned no vertices"
        )
    if unweighted_fraction > max_unweighted_fraction:
        raise RuntimeError(
            "Blender automatic weights left too many vertices unweighted: "
            f"{unweighted_vertices}/{len(mesh.data.vertices)} "
            f"({unweighted_fraction:.6f} > {max_unweighted_fraction:.6f})"
        )
    unweighted_vertices_before_nearest_fill = unweighted_vertices
    nearest_bone_filled_vertices = _fill_unweighted_from_nearest_bone(
        mesh, armature
    )
    weighted_vertices = _count_positive_deform_weights(mesh, armature)
    unweighted_vertices = len(mesh.data.vertices) - weighted_vertices
    unweighted_fraction = (
        unweighted_vertices / len(mesh.data.vertices) if mesh.data.vertices else 1.0
    )
    if unweighted_vertices:
        raise RuntimeError(
            "Nearest-bone fallback left vertices unweighted: "
            f"{unweighted_vertices}/{len(mesh.data.vertices)}"
        )
    armature_modifiers = [
        modifier for modifier in mesh.modifiers if modifier.type == "ARMATURE"
    ]
    if not armature_modifiers or armature_modifiers[0].object != armature:
        raise RuntimeError("Automatic weighting did not create a valid armature modifier")

    armature_name = armature.name
    mesh_name = mesh.name
    new_vertex_groups = len(mesh.vertex_groups)
    export_result, output_size, reimport = _export_validate_and_promote(
        output_glb,
        mesh,
        armature,
        expected_material_count=len(source_materials),
        expected_image_count=len(source_images),
        expected_uv_layer_count=len(source_uv_layers),
        expected_bone_count=source_bone_count,
    )

    result = {
        "input_glb": str(input_glb),
        "output_glb": str(output_glb),
        "import_result": list(import_result),
        "normalize_export_result": list(normalize_export_result),
        "normalize_import_result": list(normalize_import_result),
        "weld_result": list(weld_result),
        "parent_result": list(parent_result),
        "parent_world_matrix_delta": parent_world_matrix_delta,
        "weighting_method": "automatic_heat",
        "automatic_heat_parent_result": automatic_heat_parent_result,
        "automatic_heat_weighted_vertices": automatic_heat_weighted_vertices,
        "automatic_heat_unweighted_vertices": automatic_heat_unweighted_vertices,
        "unweighted_vertices_before_nearest_fill": unweighted_vertices_before_nearest_fill,
        "nearest_bone_filled_vertices": nearest_bone_filled_vertices,
        "island_cleanup": island_cleanup,
        "export_result": export_result,
        "output_size": output_size,
        "armature": armature_name,
        "bones": source_bone_count,
        "mesh": mesh_name,
        "vertices_before_weld": vertices_before_weld,
        "vertices_after_weld": vertices_after_weld,
        "welded_vertices": vertices_before_weld - vertices_after_weld,
        "old_vertex_groups": len(old_vertex_groups),
        "new_vertex_groups": new_vertex_groups,
        "old_armature_modifiers": old_armature_modifiers,
        "weighted_vertices": weighted_vertices,
        "unweighted_vertices": unweighted_vertices,
        "unweighted_fraction": unweighted_fraction,
        "weld_distance": weld_distance,
        "max_unweighted_fraction": max_unweighted_fraction,
        "source_materials": source_materials,
        "source_images": source_images,
        "source_uv_layers": source_uv_layers,
        "reimport": reimport,
    }
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Weld a rigged GLB mesh and replace MIA weights with Blender automatic weights"
    )
    parser.add_argument("input_glb_path")
    parser.add_argument("output_glb_path")
    parser.add_argument("--weld-distance", type=float, default=1e-6)
    parser.add_argument("--max-unweighted-fraction", type=float, default=0.005)
    parser.add_argument("--summary-json", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = auto_skin_glb(
            args.input_glb_path,
            args.output_glb_path,
            weld_distance=args.weld_distance,
            max_unweighted_fraction=args.max_unweighted_fraction,
        )
    except Exception as exc:  # noqa: BLE001 - worker emits structured failure
        result = {
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
        try:
            _write_json_noreplace(Path(args.summary_json), result)
        except OSError as summary_exc:
            result["summary_write_error"] = (
                f"{type(summary_exc).__name__}: {summary_exc}"
            )
        print(json.dumps(result, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    _write_json_noreplace(Path(args.summary_json), result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
