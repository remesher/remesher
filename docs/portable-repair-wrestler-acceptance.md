# Portable wrestler repair acceptance — October 21, 2026

## Outcome

**Native solid repair substantially improved the actual wrestler output.** The
fresh textured GLB has **0 seam-welded boundary edges, 65 nonmanifold edges,
1 duplicate face and 871,128 triangles**, compared with the previous undecimated
export's 21,036 boundary / 17,235 nonmanifold edges / 284 duplicates. Front,
rear and side renders show most speckling and large incorrect material patches
gone. This is a measured improvement, **not clean-manifold certification**:
removing the final duplicate diagnostically leaves 1 boundary / 65 nonmanifold
edges. No decimation or face/vertex cap was used.

**No new NVIDIA-only dependencies. No non-NVIDIA hardware certification.**
Existing approved Spark PyTorch CUDA/runtime/weights were reused. Dependency
manifests, pinned native core, global environment and active Hermes profile
were not changed. No cloud use, model downloads, CuMesh, nvdiffrast, flash-attn
or new compiled kernel package was introduced.

## Provenance and controlled settings

- Remote verified: `https://github.com/remesher/remesher.git`.
- Isolated worktree: `/home/mg/src/remesher-portable-repair`.
- Base: current PR21 `feat/native-no-decimation`,
  `8ae27196ecc62f2898613a82705a6f8877ce9df1`.
- Native core remained clean at
  `7a28332047b6af638dc6c7f72ef3481a718769fd`.
- Read both `comparison-research/legacy-vs-native.md` and `mesh-comparison.md`
  before implementation. Neither comparison report nor baseline GLB was edited.
- Prepared input SHA256:
  `daf80e42ee9d9ec1b542be545ff598b906743c4693a95f9812e23df09cfc7b94`.
- Identical single-image 512 shape generation, seed 42 / texture seed 43,
  steps 12/20/12, conditioning, quantization, model hashes, PEC unwrap,
  .0002 UV weld and 1024 texture/PBR graph. No multiview/cascade/resolution change.
- First exported a fresh decoded mesh **before unwrap**. Independent final-wheel
  generation produced **byte-identical position/index arrays** for that decoded
  stage. Its raw geometry already has defects; unwrap did not originate them.
- Only repair processing and diagnostic SaveGLB nodes were added. Default graph
  equality and unchanged sampling/texture subgraphs are programmatically checked.

## Stage experiments on one immutable decoded mesh

All table counts use the same exact-coordinate weld and undirected edge
incidence method as the previous comparison; 1e-6 quantized-weld results are
also saved. Boundaries are **edge counts, not hole counts**. Components below
are vertex-connected components; edge-connected diagnostics are separately
saved. Unused vertices in filter-only probes do not count as face components.

| Stage | Triangles | Boundary | Nonmanifold >2 | Duplicate faces | Components |
|---|---:|---:|---:|---:|---:|
| Decoded, pre-unwrap | 1,218,832 | 21,485 | 16,990 | 0 | 1 |
| Native fill only | 1,225,983 | 11,279 | 17,036 | 3 | 1 |
| UDF remesh, no cleanup | 2,317,608 | 0 | 2,404 | 0 | 60 |
| UDF inverted-component filter only | 2,308,112 | 0 | 2,176 | 0 | 14 |
| UDF enclosed-component filter only | 2,307,956 | 0 | 2,176 | 0 | 1 |
| UDF floater filter only (.005) | 2,307,956 | 0 | 2,176 | 0 | 1 |
| UDF combined component filters | 2,307,956 | 0 | 2,176 | 0 | 1 |
| Solid remesh, no cleanup | 871,824 | 0 | 88 | 0 | 6 |
| Solid + .005 component filter | 871,540 | 0 | 77 | 0 | 1 |
| Solid + filter + fill | 871,540 | 0 | 77 | 0 | 1 |
| Installed CLI/native node, repaired pre-UV | 871,540 | 0 | 79 | 0 | 1 |
| Installed CLI/native node, final UV/PBR GLB | 871,128 | 0 | 65 | 1 | 1 |

Direct experiments force `comfy.quant_ops.ck=None` **in the owned experiment
process only**, exercising native Torch/SciPy geometry fallbacks rather than
optional compiled kitchen geometry ops. Native-local runs use the unchanged
approved runtime, which advertises existing kitchen CUDA acceleration; small
numeric differences between fallback and server outputs are not hidden.

Remesh grid **512**, band 1, project_back 0, QEF off, smoothing/pole fix off,
no target-face argument, no precluster cap. This tests repair, not exact legacy
1024-remesh parity. All cleanup-disabled and individual cleanup variants were
measured separately. Solid uses fill cost 20; it is not equivalent to UDF plus
legacy inner-face flags. Hole fill uses max perimeter .03, max loop vertices 16,
no chain fill and no pre-weld. Filling the selected solid output was a no-op.

**Fill only failed as a complete repair:** it reduces open edges but increases
nonmanifold edges and introduces duplicates. **UDF plus component cleanup also
fails the intended solid semantics:** it retains connected inner sheets. Nine
fixed central torso rays intersect decoded geometry 3–6 times, cleaned UDF
8–12 times, and solid/final geometry exactly twice each. Three same-world-plane
cross-sections visibly confirm doubled UDF shells and their removal by solid.
These sparse probes are not a global self-intersection/containment certificate.

The forced-fallback solid mesh has 0 boundary / 0 nonmanifold edges **by its own
indexed connectivity** and one edge-connected face component. Exact-position
welding re-identifies coincident split sheets and yields the 77 nonmanifold
edges in the table. This distinction must not be omitted. UV export introduces
intentional chart splits; raw index boundaries of the textured GLB are not
physical holes and are not used for the comparison.

## Native semantics checked in source

Inspected `RemeshMesh`, `FillHoles`, `WeldVertices`, `_filter_components`,
`_solid_partition`, `_kitchen_op`, and DynamicCombo expansion at the pinned core.

- Solid graph cut uses SciPy Delaunay when optional geometry acceleration is
  unavailable; other geometry operations have Torch fallbacks.
- UDF is an unsigned offset shell, not an inside/outside solid classifier.
- Enclosed-component filtering uses **bbox containment OR ray parity**, despite
  its UI tooltip implying a stricter test. It is not arbitrary inner-face removal.
- Floater size is a fraction of the largest component; cleanup is vertex-based.
- Fill's edge-count/vertex-count cycle test is weaker than every degree being 2.
  Fan triangulation can add duplicates/nonmanifold edges; it is not a robust
  general-purpose large-hole triangulator.
- `WeldVertices` quantizes position bins and does not clean faces. Fill's adaptive
  pre-weld can escalate to .01 bbox diagonal; it is explicitly disabled here.
- Fill dispatches to the active Comfy device even with CPU input tensors.

A separate CPU-device smoke on Spark, optional kitchen hooks disabled, filled
a small cube opening, left a larger opening untouched, and solid-remeshed an
open cube to 1,440 vertices / 2,876 triangles with no indexed boundary or
nonmanifold edges. Initial smoke correctly failed a CPU-vs-CUDA tensor assertion
because the default active Comfy device was CUDA; it was rerun successfully
with explicit Comfy CPU policy. This tests CPU execution on Spark, not another
vendor's hardware or full CPU model inference.

## Actual installed-wheel delivery

Evidence root: `/home/mg/remesher-native-runtime/portable-repair-acceptance/`.

- Final registered-plugin job: `4ce2c599f0f645ac8e01c4cda622e10a`.
- Final wheel SHA256:
  `c63740aaec38453822e14298b4420b95d3ee9ec649956770001105d5ea292f99`.
- Final GLB: `delivery/wrestler-portable-solid.glb`, **21,423,232 bytes**,
  SHA256 `cb32a157aa068903f09a8cbd80bc5a5af50249fae2da2e6cc62cc574c22b2c02`.
- Front/rear/side textured and clay PNGs: `delivery/`.
- Actual mesh before/after contact sheet: `delivery/before-after.jpg`.
- Diagnostic stage GLBs/metrics/renders: `baseline/`, `stages/`.
- Inner-sheet evidence: `cross-sections.png`, `inner-sheet-diagnostics.json`.
- Request/history for initial decoded capture: `captured-baseline-request.json`,
  `capture-history.json`; captured live node schemas: `node-schemas.json`.
- Final graph file is explicitly **reconstructed from the installed module**:
  `repaired-graph-reconstructed.json`, not a captured final HTTP request.
- Actual plugin request/receipt/log and native child outputs are preserved under
  `hermes-home/plugin-data/remesher/jobs/<job>/`.
- `experiments.json`, `gpu-comparison.json`, `verification.json`, `manifest.json`,
  `cpu-smoke.json`, `tests.xml`, logs and reproduction scripts retain evidence.
- First-wheel run/artifacts retained separately (`gpu-first`, `delivery-first`,
  `dist-first`); all previous legacy/no-decimation baseline hashes reverified.

Actual render inspection: large leg/boot/back material corruption and most
speckling disappear. A small dark singlet spot, coarse/fused fingers, dark boots
and imperfect inferred rear anatomy remain. No new gross hand/leg gap bridge
was visible in these front/rear/side views. Surface offset/filleting and
sub-voxel closures remain possible. Renders are orthographic CPU triangle
rasterizations with baked albedo and approximate diffuse light, **not full PBR**.
Texture resolution/latent sampling were not improved; this does not prove which
individual postprocessing/bake interaction caused each formerly dark pixel.

## Verification, resources and review status

- Built wheel offline, installed only in a new isolated CLI venv using cached
  dependencies, and invoked actual registered plugin → installed CLI → owned
  native server → GPU generation → repaired UV/PBR GLB. Installed source hashes
  match the candidate. Setup plan/check/apply passed, all four model hashes
  reverified without downloading anything.
- Final installed-wheel suite: **229 passed + 53 subtests**, zero skips/errors/
  failures; JUnit 282 cases. Both real CLI protocol fixture partitions enabled.
  Base with identical test dependencies: 209 passed + 53 subtests, zero skips.
  Protocol fixtures are not the GPU evidence above. RED failures preceded each
  new graph/CLI/plugin behavior.
- Changed backend/plugin/new-test Ruff checks and `git diff --check` pass.
  Full legacy CLI file has 72 pre-existing Ruff diagnostics in both base and
  candidate; line-number shifts are not new findings.
- All owned compute scopes: MemoryMax **64 GiB**, MemoryHigh **56 GiB**, swap
  **2 GiB**. Final plugin wall time **34.07 s**; peak cgroup RAM
  **5,960,572,928 bytes**, zero high/max/OOM events. Forced-fallback experiment
  peak cgroup RAM 2,574,413,824 bytes. These are not GPU-allocation peaks.
- Owned child processes exited; fish-speech PID **1803186**, port **18080**,
  remained alive. No unrelated server was interrupted.
- Self-review completed. Independent Codex read-only review was **blocked** by
  bubblewrap networking permissions. Supplied-source review packet preparation
  then required approval; the gate was not bypassed or retried. Independent
  review was pending at the time of this experiment. Current integration readiness
  is tracked separately in the [release task index](release-readiness.md).
- Existing GB10/PyTorch capability warning remains; actual runs succeeded.
  No claims of pristine manifold topology, other-hardware compatibility,
  legacy resolution/multiview parity, rigging or manufacturing readiness.
