# Opt-in native portable mesh repair

The default graph remains unchanged. Repair is experimental and requires native
ComfyUI at the pinned revision documented in `native-comfy-backend.md`, plus
`--no-decimation`. It uses existing native **PyTorch/SciPy** mesh nodes. This
feature adds **no NVIDIA-only dependencies**, CuMesh, nvdiffrast, flash-attn,
custom node, model download, or runtime installation. Existing PyTorch CUDA
execution is allowed; this is **not a claim of non-NVIDIA hardware testing**.
Native core may use already-installed optional comfy-kitchen acceleration; its
Torch/SciPy geometry fallback was tested separately with those hooks disabled.

```sh
comfy-prompt-cli image-to-glb \
  --backend native-local --native-config /absolute/native-setup.json \
  --image /absolute/prepared.png --no-decimation \
  --mesh-repair solid --repair-resolution 512 \
  --repair-max-perimeter 0.03 --repair-drop-small-components 0.005
```

The installed Hermes plugin accepts matching per-job inputs:

```json
{
  "image": "/absolute/prepared.png",
  "no_decimation": true,
  "mesh_repair": "solid",
  "repair_resolution": 512,
  "repair_max_perimeter": 0.03,
  "repair_drop_small_components": 0.005,
  "timeout_seconds": 1800
}
```

These are opt-in generation settings, not permission to install dependencies or
raise memory limits. Existing configured runtime paths, process ownership,
output isolation and setup readiness checks remain in effect.

## Modes and order

- `none` (default): identical prior graph; no repair nodes or extra exports.
- `fill`: decoded mesh → small-hole fill → existing UV/PBR pipeline. It is a
  diagnostic option, **not recommended as a complete repair** for the wrestler.
- `solid`: decoded mesh → native narrow-band solid dual contouring → disconnected
  component filtering → small-hole fill → existing UV/PBR pipeline.

There is no DecimateMesh node in either repair graph. Native remesh's hidden
pre-clustering is explicitly disabled with `precluster_max_verts=0`. There is
**no face or vertex cap**. A remesh grid can produce fewer or more faces than the
input; that is surface re-extraction, not a target-face simplification.

Solid mode explicitly selects `sign_mode=solid`, `fill=20`, `qef=false`, `band=1`,
`project_back=0`, `fix_poles=false`, `smooth_iters=0`. DynamicCombo children use
the pinned core's dotted API fields (`sign_mode.fill`, `sign_mode.qef`). The
client validates the selected child schema before upload.

`repair_resolution` (32–2048, default 512) controls only the remesh grid. It does
not change the 512 image-to-shape generation preset, seeds, quantization,
sampling, conditioning, multiview behavior or 1024 UV/texture resolution.
High remesh resolutions can need substantial memory; no admission-limit bypass
or memory allocation change is implicit.

`repair_drop_small_components` is a fraction of the **largest component's face
count**, not a face budget. Default .005; 0 disables. Native filtering uses
vertex connectivity and cannot remove inner sheets connected to the exterior.
It can remove legitimate small disconnected accessories; inspect your result.
Solid graph-cut inside/outside classification, rather than this component
filter, is the important operation for the wrestler's connected inner sheets.

`repair_max_perimeter` is in mesh coordinate units (not a fraction of the bbox),
limited here to 0–.03; 0 skips hole filling. The graph always disables pre-weld
(`weld_epsilon_rel=0`) and open-chain filling, and limits each boundary candidate
to 16 vertices. This is not a total mesh vertex cap. The native filler uses
small vertex/centroid fans, not a general robust polygon triangulator. Its
cycle test compares component edge/vertex counts, which is weaker than checking
every boundary degree is two; even this conservative fill can introduce
nonmanifold edges/duplicate triangles on pathological input. Do not interpret
it as guaranteed safe arbitrary-hole closure. The tested solid mesh was already
closed and filling was a no-op.

## Evidence and limitations

When repair is enabled, two additional native SaveGLB outputs preserve decoded
and repaired **pre-unwrap** geometry with `_decoded` and `_repaired` filename
suffixes. In `native-local`, they remain in the retained owned run's `output/`
alongside its server log. With an existing native server they remain in that
server's output directory. The CLI/plugin downloads and advertises only the
final textured GLB; it does not claim the stage exports are plugin assets.

UV unwrap remains unchanged, including its .0002 relative weld; it can merge
or split vertices and discard collapsed triangles. Texture remains conditioned
on the original shape latent and is baked using the original reference mesh:
this does **not** reproduce the legacy repaired-mesh re-encoding/multiview
texture pipeline.

Solid mode can close intentional openings and bridge sub-voxel gaps; inspect
hands, legs, clothing creases and accessories in front/rear/side clay and textured
views. Do not use a zero-boundary count as a self-intersection, watertight-volume,
rigging or manufacturing certificate. Read
[`portable-repair-wrestler-acceptance.md`](portable-repair-wrestler-acceptance.md)
for actual stage measurements and remaining defects.
