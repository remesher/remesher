# Pixal3D native acceptance — October 21, 2026

## Outcome

**The installed wheel/plugin pipeline passed; this wrestler failed visual quality.**
Pixal3D generated a real single-image mesh, native solid repair ran, and UV/PBR
GLB export completed. The result has severe rod-like elongated fingers/hands.
Those are already visible in the decoded pre-repair clay render; solid repair
is not their origin. Do **not** replace the better TRELLIS delivery with this
artifact or call lower edge-defect counts an anatomy improvement.

| Exact-position welded stage | Triangles | Boundary edges | Nonmanifold edges >2 | Duplicate faces |
|---|---:|---:|---:|---:|
| Pixal3D decoded, before repair | 591,632 | 15,635 | 31,738 | 0 |
| Pixal3D solid repair, before UV | 455,660 | 0 | 25 | 0 |
| Pixal3D final UV/PBR | 455,480 | 0 | 11 | 0 |
| Latest TRELLIS solid final (unchanged) | 871,128 | 0 | 65 | 1 |

Counts use the same helper as PR22 and are also measured with 1e-6 quantized
position welding. These are edge counts, not holes. Both final meshes have one
vertex-connected face component. Neither is certified clean-manifold,
self-intersection-free or manufacturing-ready. No decimation or vertex/face cap.

## What changed

- Schema-v1 setup config adds explicit `model: trellis2 | pixal3d`, retaining
  TRELLIS for existing configs. Root-based plan/check/apply accept `--model`.
  Config-based selection is authoritative: conflicting model flags fail closed.
- Each setup operation uses only the selected preset's manifest. Pixal3D shares
  identical VAE/DINO files and adds only official pinned diffusion + MoGe assets.
  Download approval remains explicit and invocation-local; no package install
  flag was used for this acceptance.
- Plugin config validation, status selection and per-job snapshots propagate the
  selected model to the actual installed CLI; active Hermes settings untouched.
- Pixal3D graph uses the pinned single-image `camera_angle_x` contract, fed by
  MoGe horizontal FoV in **degrees**, not the multiview `fov` contract.
- Owned child model paths now include `geometry_estimation`. Native V3 `COMBO`
  options are checked before upload, as well as older list-form enums.

## Reproduction and model provenance

Runtime/evidence root: `/home/mg/remesher-native-runtime/pixal3d-acceptance/`.
Worktree: `/home/mg/src/remesher-pixal3d`, branch `feat/native-pixal3d`, stacked
on remote-verified PR22 `3a5f3eb8fdfce0960e29f5efe07ca688eca7a8ae`.
No parent branch was modified or merged.

- Native ComfyUI remains clean at `7a28332047b6af638dc6c7f72ef3481a718769fd`
  (reports 0.42.0); Python 3.12.9, aarch64, NVIDIA GB10, PyTorch 2.10.0+cu130,
  comfy-kitchen 0.2.39, comfy-aimdo 0.5.6. No new NVIDIA-only dependencies,
  global installs, cloud compute or runtime-source edits.
- Existing approved `combined-acceptance/runtime-overlay` reused. Existing
  optional kitchen CUDA acceleration remained enabled, as in PR22's real
  server run. Repair uses the same native nodes with previously validated
  Torch/SciPy fallbacks; **this is not a fresh forced-fallback or CPU/MPS/ROCm
  inference certification**.
- Diffusion: `Comfy-Org/Pixal3D`, revision
  `f37641be376725d324c56626007cc477f1249a69`,
  `diffusion_models/pixal3d_int8_convrot.safetensors`, **5,584,555,824 bytes**,
  SHA256 `4621eac3b715484f79303c7152af641fe0b2b14f4d0e3d394fd6922d00f955ec`.
- MoGe: `Comfy-Org/MoGe`, revision
  `1484985258ba7ef45c314144fcf0e90924ffbf44`,
  `geometry_estimation/moge_2_vitl_normal_fp16.safetensors`, **661,859,924 bytes**,
  SHA256 `cb1a692d03235671e959e81360d7b4d9f44aefadb1f852d6ca6aa17799d5e31f`.
- Total newly downloaded bytes **6,246,415,748**. The existing deduplicated
  evidence manifest and official pinned Hub metadata agree. Downloaded through
  the installed `native-setup apply --config ... --allow-download`; shared
  weights were hash-verified and reused. Final plan/check/apply pass with no
  download flag and all five hashes verified.
- Prepared input is byte-identical to PR22:
  `combined-acceptance/wrestler-prepared.png`, SHA256
  `daf80e42ee9d9ec1b542be545ff598b906743c4693a95f9812e23df09cfc7b94`.

## Controlled comparison and limitations

Kept seeds 42/43, single 512 shape pass, sampling steps 12/20/12, shared VAE/DINO,
solid grid512/fill20/band1/project_back0/QEF off/pole fix off/precluster0,
small-component threshold .005, conservative fill .03/max16/no pre-weld/no
chain fill, PEC UV/weld .0002 and 1024 PBR bake unchanged. Programmatic graph
comparison finds **only** model and conditioning changes plus the three MoGe
nodes. Default TRELLIS graph remains identical.

Inspected pinned core schemas and official combined editor template revision
`d0e41fe5423f93db5b5872cf273d7b1af8aa68bc`: the shared structure and 512-shape
sampling nodes use these settings for either selected model. This does **not**
claim parity with its later cascade or with upstream Pixal3D's tighter crop.
The controlled input retains TRELLIS's larger margin; source tooltip recommends
pad_factor1.1 for Pixal3D. Different crop/preprocessing is a separate experiment,
not silently substituted into this same-input comparison.

Independent identical-image/settings MoGe diagnostic estimated horizontal FoV
**42.75103780924466°** (not a captured scalar from the plugin job). A second real
installed-CLI run with fixed **49.13°** still has elongated fingers: 454,408
triangles, 0 boundary / 15 nonmanifold edges, no duplicates. Thus changing only
this FoV value did not fix the defect. No claim that upstream Pixal3D itself is
broken, or that preprocessing, resolution or another seed would not help.

Front/rear/side textured and clay renders were inspected. Pixal3D is also more
oblique/asymmetric and changes inferred anatomy; its inflated sideways hand
shapes are obvious in side view. The CPU raster previews use baked albedo and
approximate diffuse shading, not full metallic/roughness rendering. PBR image
and UV presence are separately verified in the actual GLB.

## Artifacts and test evidence

- Final plugin job `b7d414d0d51543bb9e2aaba18bd3004f`.
- `delivery/wrestler-pixal3d-solid.glb`, **11,734,116 bytes**,
  SHA256 `d3b9fbc251a06425b7253a48483675bf598f443feb4724b471b1c89a6359e7fb`.
- `delivery/{front,rear,side}-{textured,clay}.png` and
  `delivery/trellis-vs-pixal3d.jpg` show actual meshes; label Pixal3D provisional.
- `stages/` includes decoded, repaired, final, TRELLIS comparison and fixed-FoV
  metrics/renders. `gpu-comparison.json`, `material-evidence.json`,
  `moge-diagnostic.json`, `live-node-schemas.json`, `official-template.json`,
  `official-source-verification.json`, `verification.json`, `manifest.json`.
- `graph-reconstructed.json` is explicitly reconstructed from the installed
  module, **not** a captured final request. Actual plugin request, receipt,
  CLI/server logs and native outputs are retained under `hermes-home/`.
- Final wheel SHA256
  `26e7521e823aa5394385aa7b301f0de68eef3adef6befb5b392c39ec90c40d63`.
  All six changed package files match installed source hashes.
- Installed-wheel suite: **236 passed + 53 subtests**, JUnit **289**, zero
  skipped/failures/errors; both actual-CLI protocol fixture partitions enabled.
  Protocol fixtures are separate from the real GPU job above. RED failures
  observed before new preset, download allowlist, graph, routing, model-path
  propagation and V3 enum validation implementations.
- Final plugin wall time about **33.06 s**; peak cgroup RAM **9,819,090,944 bytes**,
  not a GPU allocation peak. Owned scopes capped at 64 GiB / high56 GiB / swap2
  GiB, with zero high/max/OOM events. All owned children exited. Existing
  fish-speech PID1803186 and port18080 remain alive.

## Failures retained and release state

Initial real run rejected the MoGe model enum because its category was absent
from the owned child's extra-model-paths config. Fixed with a failing regression
and reran the actual installed plugin successfully. That failure also exposed
missing V3 COMBO preflight checking; fixed test-first, rebuilt the final wheel
and ran a fresh successful GPU job. No placeholder output was substituted.

Existing PyTorch GB10 capability warning remains. Standalone MoGe diagnostic
returned its result but emitted a model-patcher destructor warning on interpreter
shutdown; the real plugin run did not fail. Download/setup required no upstream
patch. **Visual quality remains failed; independent review/CI are separate
pending gates.** This is a stacked draft PR, not merge-ready.
