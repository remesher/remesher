# Explicit native normals and named single-image quality preset

## Scope and configuration

PR27's final bounded delta adds `--native-preset quality-1536-solid768` and
`--native-preset fast`, plus an explicit `MeshSmoothNormals(crease_angle=180)`
node immediately before final `SaveGLB`. Both TRELLIS.2 and Pixal3D, through
both `native` and `native-local`, use the same export tail.

The recommended **explicitly selected** quality preset resolves to:

| Control | Value |
|---|---|
| Shape | 512 → 1536 learned-coordinate cascade, 12-step Euler/simple refinement |
| Repair | solid, resolution768; component threshold0.005 |
| Global simplification | no DecimateMesh; precluster_max_verts=0 |
| Remesh extras | fix_poles=false, smooth_iters=0, project_back=0 |
| Bounded fill | perimeter0.03, max_vertices16 per hole, no chains or pre-weld |
| UV/PBR atlas | 4096 |
| Final normals | smooth180, explicit glTF NORMAL; no geometry mutation |

`fast` preserves 512/no-repair/1024/80000-face behavior, now with smooth normals.
No preset preserves existing CLI defaults, including the legacy `comfy3d`
backend. No existing caller is silently opted into a heavy generation job.

With a preset, matching explicit controls are accepted, conflicting controls
are rejected before upload/runtime startup. Any explicit face target conflicts
with quality, even80000. Custom combinations require omitting the preset.
Seeds, camera, model and runtime controls remain independent. The CLI reports
resolved controls; the plugin configuration script reports them without launch.

Hermes settings accept `native_preset`; without a settings file the equivalent
is `REMESHER_NATIVE_PRESET`. Settings JSON remains authoritative over environment.
The request preset overrides the configured preset. Request scalar controls
supersede settings scalar controls, but must agree with the selected preset.
Recommended setup examples and both bundled skills select quality explicitly;
normal generation then only needs the prepared `image`. No active user profile
was edited. See [installation and examples](native-installation.md).

## Export audit and repeatable regression

The immutable native runtime is
`ComfyUI@7a28332047b6af638dc6c7f72ef3481a718769fd`.
Its `MeshSmoothNormals`180 path shallow-copies the MESH, computes area-weighted
normals, and shares normals across quantized coincident positions without
changing vertex/index layout. `SaveGLB.execute` calls
`mesh_item_to_glb_bytes`, which slices `mesh.normals` and passes them into
`save_glb`; that writer explicitly emits a NORMAL accessor. No runtime/exporter
patch or NVIDIA-only dependency is needed. Normals are added after all topology,
UV and material stages, not merely attached to a decoded mesh that unwrap might
replace. Tangents are not needed for this material path, which has no normal map.
Raw decoded/repaired diagnostic saves remain unchanged.

`scripts/verify-native-normals.py` is a real CPU native-export regression using
an already installed native runtime and CLI wheel. It restores the saved final
GLB's indexed arrays and texture pixels, runs the candidate graph's smooth-normal
tail and the exact serializer used by SaveGLB, then parses the output GLB bytes.
It does not use a library that silently synthesizes imported normals.

Checks include missing-NORMAL failure on the original file; NORMAL count matches
POSITION; all values finite/unit length; exact POSITION/index/UV equality;
identical material JSON and embedded image pixels; and equal normals on exact
coincident UV-seam positions. The script refuses an existing output directory.
No UV packing, shape generation, texture diffusion or repair is repeated.

## Fixed wrestler evidence

Fresh evidence root:
`/home/mg/remesher-native-runtime/pr27-normals-quality/`.
Source assets are the immutable accepted files in
`final-dual-model-wrestler-acceptance/delivery/` (1536/solid768/4096/uncapped).
The built-wheel repeat is in `wheel-trellis2/` and `wheel-pixal3d/`.

| Model | NORMAL count | Triangles | Length range | Output SHA256 |
|---|---:|---:|---|---|
| TRELLIS.2 | 509792 | 911952 | 0.9999999403953552–1.0 | `0f981c71cc3a02730b363a6890f95ad335dcbbf8828549154a69b19a008089dc` |
| Pixal3D | 299133 | 525742 | 0.9999999403953552–1.0 | `79fcbc6370f29379b764048ec3537eb7634084c925cfd96426d19ec9e4fc98de` |

Both runs report CPU tensors, exact geometry/UV/index preservation and identical
materials/image pixels. Source and installed-wheel runs produce identical final
bytes. `verification.json` includes the original and output hashes, and
`graph.json` records each model's resolved candidate graph.

`trellis2/before-after.png` and `pixal3d/before-after.png` show actual-mesh
front/rear/side textured and gray software renders, before on top and after
below. The renderer explicitly interpolates exported normals in the after row;
it does not invent smooth normals for the baseline. This is approximate diffuse
lighting, not a full PBR renderer. Silhouettes/anatomy remain the same; smooth
shading reduces fine faceting, not missing geometry. Coarse/fused hands and
inferred-back texture discoloration remain, particularly the Pixal back/shoulder
patches. There is no new quality-ranking claim.

## Verification boundaries

Graph/CLI conflict tests were observed failing before implementation. The saved
actual GLBs fail the NORMAL assertion before the new export tail; both corrected
native outputs pass. CPU tests include real installed CLI/plugin transport through
both backends and both model selections (the HTTP child is a protocol fixture,
not inference). The full suite, isolated wheel contracts, focused lint and real
pinned Hermes SDK validator are required. Hosted canonical CI must pass on the
exact pushed candidate; the release owner handles final independent review.

This delta consumes the complete final parity audit rather than reopening older
512-only/no-repair conclusions. It closes the explicit-normal and safe preset
selection gaps only. Single-image native functionality remains **provisional
quality**, not exact original/legacy/reference parity. Multiview, repaired-mesh
re-encoding/retexture, normal/AO maps and automatic background removal remain
out of scope. Sampling, precision, camera/preprocessing and replacement algorithm
differences remain. Prior welded nonmanifold edges remain unchanged; this is not
manifold, watertight, print-ready or non-NVIDIA-inference certification.

No full generation, model download, global installation, cgroup change, service
replacement, merge, protection, catalog or release operation was performed.
Native export was CPU-only in the existing runtime environment; this does not
certify an otherwise unchanged runtime without its installed acceleration stack.
