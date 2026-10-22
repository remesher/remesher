# Controlled Pixal3D 512 → 1536 wrestler acceptance

## Outcome (provisional quality, not release approval)

**The real installed CLI and Hermes plugin completed the official two-node
1536 shape cascade on the GPU. Face/beard, hair grooves and clothing/boot
geometry are visibly more defined than the padded 512 control. This is a
partial quality improvement, not an unqualified replacement:** hands remain
coarse/fused, and the new textured rear/side has pronounced dark arm/shoulder
patches and a pale lower-back patch. The inferred singlet back also changes.
Clay views do not show corresponding large missing arm surfaces, so do not
label those dark regions geometric holes. No 4096-atlas or remesh768 trial ran.

512 solid repair visibly softens some of the newly decoded beard/hair/boot
features. Major improvements survive, but raw 2,809,192 faces become 230,056
repaired faces through remeshing, **not decimation or a vertex cap**. Polygon
counts alone are not a quality metric. Raw and repaired meshes are preserved.
The repaired/final mesh still has nonmanifold edges: it is not certified
manifold, print-ready or anatomically accurate.

## Reproducible boundary

- Application base: PR24 `3f42107fa0935033b4554b1ea7fa46acee918273`, live head
  checked before creating `feat/pixal-official1536` in its own worktree.
- Pristine runtime: `7a28332047b6af638dc6c7f72ef3481a718769fd`; reused existing
  verified environment, Pixal INT8 ConvRot bundle, DINO/NAF and shape/texture VAEs.
  No weights downloaded or NVIDIA-only extensions installed.
- Actual path: isolated Hermes home → registered `remesher_generate` handler →
  newly built/installed wheel → saved setup config/private snapshot → owned
  native ComfyUI GPU child. Active Hermes configuration was not changed.
- Exact existing `pixal3d-padding-acceptance/wrestler-padding25.png` bytes;
  SHA256 verified against its preparation record, not regenerated or recropped.
- Frozen horizontal FOV `42.75103780924466`; seeds structure/shape/refine/texture
  `42/42/42/43`. Original automatic FOV was independently reproduced in the
  earlier padding experiment, not recovered from its oldest main-run receipt.
- Initial samplers, quantization, solid repair512/smoothing0/precluster0,
  FillHoles settings, no decimation and UV/PBR1024 all unchanged.
- Added `shape_upsample` target1536 and `shape_refine` seed42,12 steps,CFG7.5,
  Euler/**simple**,denoise1,existing shape_model; exactly four required rewires.
  Queue-captured executed graph equals the proposed graph after normalizing
  only uploaded image and per-job output prefix. Default512 exactly equals
  the saved historical padded control graph.

## Execution and resources

Pristine GPU job `2f3ca138b6bc4730a1fe7c640dcab3eb` succeeded; server execution
29.44 seconds, monitored plugin wall time 40.41 seconds. The actual executed
graph is saved from `/queue` while running. The server's completed `/history`
was not captured before immediate owned-child cleanup; successful plugin state,
server log and actual exported assets are retained, not a reconstructed history.

The owned systemd cgroup verified `memory.max=68719476736` (64GiB),
`memory.high=60129542144` (56GiB), `memory.swap.max=2147483648` (2GiB).
Recorded peak cgroup usage was **8.299GiB**; minimum sampled host MemAvailable
**77.484GiB**, safely above the 16GiB stop floor. Memory events high/max/OOM/OOM
kill were zero. These are cgroup accounting numbers, not total GPU memory.
Fish-speech PID1803186 was unchanged. Runtime PID/port closed and scope removed.
No resource expansion or fallback occurred.

### Actual resolution/dtype diagnostic

A second, explicitly diagnostic run used the same installed wheel/plugin,
existing weights and an isolated worktree of the same pinned runtime with only
three observational print statements. Its log records:

- Upsample requested/actual **1536**, coordinate grid **96**, **4235** tokens.
- Shape decoder actual mesh resolution **1536**, latent `[1,32,4235,1]`,
  latent FP32, VAE compute FP16.
- Texture voxel resolution **1536**, coordinate grid96 (atlas remains1024).
- Checkpoint storage INT8 ConvRot; model compute/manual cast BF16, VAE FP16.
- CUDA allocator peak through texture decode: 3,453,688,376 allocated bytes,
  3,791,650,816 reserved bytes. This excludes non-allocator/dynamic-weight
  memory and is not a whole-device peak measurement.

Diagnostic raw and repaired vertices/faces are **bit-identical** to the pristine
run. Final vertices/faces also match, but UVs and texture pixels differ across
runs; no full-byte determinism claim. Delivered previews/assets use the first,
pristine runtime run, not the instrumented duplicate.

The first instrumentation attempt correctly failed setup's pinned-clean-checkout
gate. Its job/log is preserved (`a34747487bd14939a3231c79e789f3d2`). The subsequent
instrumented run used supported explicit runtime paths without saved setup,
with only an owned extra-model-paths file pointing at existing weights. No
production clean-checkout check was weakened. This was an instrumentation
setup limitation, **not an upstream 1536 bug**; no runtime algorithm fix needed.

## Geometry, exact-position welded

| Stage | Vertices | Faces | Boundary edges | Nonmanifold edges >2 |
|---|---:|---:|---:|---:|
| Padded512 raw | 142,243 | 305,570 | 8,795 | 24,005 |
| Padded512 repaired | 115,874 | 231,744 | 0 | 8 |
| Padded512 final | 132,818 | 231,678 | 0 | 6 |
| Cascade1536 raw | 1,361,921 | 2,809,192 | 60,388 | 114,071 |
| Cascade1536 repaired | 115,030 | 230,056 | 0 | 18 |
| Cascade1536 final | 134,339 | 229,942 | 0 | 14 |

Tolerance1e-6 results and connected components are in `geometry.json`. Boundary
edge count is not hole count. No all-pairs distance matrix was constructed.

## Artifacts and visual comparison

Evidence root: `/home/mg/remesher-native-runtime/pixal-official1536-acceptance/`.

- `delivery/wrestler-pixal3d-1536-final.glb`: **6,645,932 bytes**;
  SHA256 `54bbfab7c690bd74103d8d04ea265b83ef1aecfc2f24956cb9ae7bcbbff662dd`.
- `delivery/wrestler-pixal3d-1536-raw.glb`: **50,060,080 bytes**;
  SHA256 `c91d34e1fecc31cac7936f9b401d4fc7e3f7ac3685a6eebbba19464b96eb11c2`.
- `delivery/wrestler-pixal3d-1536-repaired.glb`: **4,147,752 bytes**.
- `delivery/close-comparison-final-textured.png`,
  `close-comparison-final-clay.png`, `close-comparison-raw-clay.png`:
  top=padded512, bottom=cascade1536; front/rear/side, labeled PROVISIONAL.
- `delivery/1536-stages-clay.png`: raw/repaired/final, front/rear/side.
- `shared-camera-close/`: individual views; shared height-normalized
  orthographic camera, 600px views, same rotations and lighting. Base-color
  textured CPU raster, not a full physically based renderer. Raw meshes have
  no texture. Wider-camera sheets are also retained.
- `executed-graph.json`, `queue.json`, `expected-graph.json`, `verification.json`,
  `geometry.json`, `memory.json`, `provenance.json`, `result.json`, `summary.json`,
  server logs, installed wheel and instrumentation patch/comparison retained.

## Tests and delivery state

Strict RED→GREEN observed for exact graph patch, invalid resolution, CLI routing
and plugin shape/FOV forwarding/rejection. Full suite with both installed-CLI
contract environment variables: **253 passed, 53 subtests passed, zero skips**.
The earlier default run's five optional skips were subsequently exercised.
`git diff --check` passes. Installed-wheel protocol fixtures are separate from
real GPU acceptance above.

Implemented and live-verified; **independent review and remote CI remain separate
release gates**. This experiment is now included in the integrated source;
see [current release status](release-readiness.md), not historical branch targets.
Do not claim full official preset parity, general hardware portability or a
uniform quality upgrade from this one controlled asset.
