#!/usr/bin/env python3
"""CPU-only fixed-mesh native export acceptance (not model inference).

Run with an already provisioned native runtime Python and installed CLI wheel:
  python verify-native-normals.py --checkout /absolute/ComfyUI \
      --input /absolute/final.glb --output /absolute/new-evidence --model trellis2
No downloads, runtime edits, custom nodes or new weights. Output must not exist.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import struct
import sys


def read_glb(raw):
    import numpy as np
    assert struct.unpack_from('<4sII', raw) == (b'glTF', 2, len(raw))
    size, kind = struct.unpack_from('<II', raw, 12)
    assert kind == 0x4E4F534A
    doc = json.loads(raw[20:20 + size])
    offset = 20 + size
    size, kind = struct.unpack_from('<II', raw, offset)
    assert kind == 0x004E4942 and offset + 8 + size == len(raw)
    binary = raw[offset + 8:]
    assert all(set(n) <= {'mesh', 'name'} for n in doc['nodes'])
    assert len(doc['meshes']) == 1 and len(doc['meshes'][0]['primitives']) == 1
    primitive = doc['meshes'][0]['primitives'][0]
    assert primitive.get('mode', 4) == 4
    def accessor(index):
        a = doc['accessors'][index]
        b = doc['bufferViews'][a['bufferView']]
        dtype = np.dtype({5126: '<f4', 5125: '<u4', 5123: '<u2'}[a['componentType']])
        width = {'VEC2': 2, 'VEC3': 3, 'SCALAR': 1}[a['type']]
        return np.ndarray((a['count'], width), dtype=dtype, buffer=binary,
            offset=b.get('byteOffset', 0) + a.get('byteOffset', 0),
            strides=(b.get('byteStride', width * dtype.itemsize), dtype.itemsize)).copy()
    arrays = {k: accessor(v) for k, v in primitive['attributes'].items()}
    arrays['indices'] = accessor(primitive['indices'])
    images = []
    from PIL import Image
    for image in doc.get('images', []):
        view = doc['bufferViews'][image['bufferView']]
        start = view.get('byteOffset', 0)
        images.append(np.asarray(Image.open(io.BytesIO(binary[start:start + view['byteLength']])).convert('RGB')))
    return doc, arrays, images


def assert_normals(arrays):
    import numpy as np
    assert 'NORMAL' in arrays, 'export is missing NORMAL'
    normals = arrays['NORMAL']
    assert normals.shape == arrays['POSITION'].shape
    assert np.isfinite(normals).all()
    lengths = np.linalg.norm(normals, axis=1)
    assert np.allclose(lengths, 1.0, atol=2e-5), (lengths.min(), lengths.max())
    return {'count': len(normals), 'min_length': float(lengths.min()),
            'max_length': float(lengths.max()), 'finite_unit': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', type=Path, required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model', choices=['trellis2', 'pixal3d'], required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    # Select CPU BEFORE native model management imports. No inference is run.
    sys.path.insert(0, str(args.checkout.resolve()))
    sys.argv = [sys.argv[0], '--cpu', '--disable-metadata']
    import comfy.options
    comfy.options.enable_args_parsing()
    import torch
    import numpy as np
    from comfy_api.latest import Types
    from comfy_extras.nodes_mesh_postprocess import MeshSmoothNormals
    from comfy_extras.nodes_save_3d import mesh_item_to_glb_bytes
    from comfy_prompt_cli.native_backend import build_prompt
    from comfy_prompt_cli.native_presets import PRESETS
    preset = dict(PRESETS['quality-1536-solid768'])
    preset['shape_resolution'] = preset.pop('native_shape_resolution')
    preset['atlas_resolution'] = preset.pop('native_atlas_resolution')
    graph = build_prompt('fixed-saved-input.png', model=args.model, **preset)
    (args.output / 'graph.json').write_text(json.dumps(graph, indent=2))
    raw = args.input.read_bytes()
    doc, before, images = read_glb(raw)
    # RED evidence from the saved acceptance artifact, not a synthetic substitute.
    try:
        assert_normals(before)
    except AssertionError as exc:
        baseline = str(exc)
    else:
        raise AssertionError('baseline unexpectedly already contains valid normals')
    pbr = doc['materials'][0]['pbrMetallicRoughness']
    def texture(field):
        return torch.from_numpy(images[doc['textures'][pbr[field]['index']]['source']].copy()).float().div(255)[None]
    mesh = Types.MESH(torch.from_numpy(before['POSITION'])[None],
        torch.from_numpy(before['indices'].astype(np.int64).reshape(-1, 3))[None],
        uvs=torch.from_numpy(before['TEXCOORD_0'])[None],
        texture=texture('baseColorTexture'),
        metallic_roughness=texture('metallicRoughnessTexture'))
    tail = graph[graph['save']['inputs']['mesh'][0]]
    assert tail['class_type'] == 'MeshSmoothNormals'
    assert tail['inputs']['mesh'] == ['textured', 0]
    result = MeshSmoothNormals.execute(mesh, tail['inputs']['crease_angle'])[0]
    assert result.vertices is mesh.vertices and result.faces is mesh.faces
    assert result.uvs is mesh.uvs and result.texture is mesh.texture
    assert result.metallic_roughness is mesh.metallic_roughness
    # This is exactly SaveGLB's serializer, not trimesh (which can regenerate normals).
    exported = mesh_item_to_glb_bytes(result, 0)
    target = args.output / (args.model + '-smooth.glb')
    target.write_bytes(exported)
    after_doc, after, after_images = read_glb(target.read_bytes())
    normal_report = assert_normals(after)
    for key in ('POSITION', 'indices', 'TEXCOORD_0'):
        assert np.array_equal(before[key], after[key]), key
    assert doc['materials'] == after_doc['materials']
    assert len(images) == len(after_images)
    for old, new in zip(images, after_images):
        assert np.array_equal(old, new)
    # Coincident UV seam positions get the same smooth normal, without welding indices.
    _, inverse = np.unique(after['POSITION'], axis=0, return_inverse=True)
    mins = np.full((inverse.max() + 1, 3), np.inf)
    maxs = np.full_like(mins, -np.inf)
    np.minimum.at(mins, inverse, after['NORMAL'])
    np.maximum.at(maxs, inverse, after['NORMAL'])
    assert np.max(maxs - mins) == 0
    report = dict(model=args.model, device=str(result.vertices.device),
        baseline_normal_failure=baseline, input=str(args.input), output=str(target),
        input_sha256=hashlib.sha256(raw).hexdigest(),
        output_sha256=hashlib.sha256(exported).hexdigest(), normals=normal_report,
        geometry_uv_indices_exact=True, material_and_image_pixels_exact=True,
        coincident_seam_normals_equal=True, triangles=int(after['indices'].size // 3),
        tangent_required=False, inference_run=False,
        exporter='native SaveGLB mesh_item_to_glb_bytes',
        scope='CPU fixed saved final mesh; no UV regeneration or model inference')
    (args.output / 'verification.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
