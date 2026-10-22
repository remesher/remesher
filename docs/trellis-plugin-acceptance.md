# Combined TRELLIS / Hermes acceptance

## Result

**Real end-to-end generation passed** on code commit
`808a5de953725995c00783df6e5df2d4b3571b66`, combining PR18
`cb93186033278c17107b4a4141300353e58e0dfa` and PR19
`3fb88420d0da916b3df5f3fe5672ff9d9d93b439` in an isolated worktree.
No PR was merged and neither original PR branch was rewritten.

The actual registered plugin handler submitted a fresh wrestler input through
an isolated, freshly built wheel CLI, config-based `native-local`, an owned
pinned ComfyUI child, all TRELLIS sampling/decoding and UV/PBR export stages,
and the plugin's persistent artifact readback. This is not an HTTP fixture or
reuse of a historical wrestler GLB. No active Hermes profile plugin/config
was installed or changed. No Pixal3D model was downloaded or executed.

## Exact local evidence and artifacts

Evidence root: `/home/mg/remesher-native-runtime/combined-acceptance/`.

- Input: `/home/mg/wrestler-front-1up.png`, unchanged SHA256
  `20f5c1c18bfc9a1ceb3c8dc6c0eee67a93ae79db26a0aedfea65ae57aae8b122`.
- Real existing BiRefNet via pinned native ComfyUI loader generated
  `wrestler-mask.png`; `wrestler-prepared.png` is a black square composition
  with 17.5% margin on each side of its long dimension. Both hands, boots,
  head and gray singlet were visually retained. No simple color thresholding.
- Final job: `504de438d27348ef839ca7a5f7b20a43`.
- Delivery: `delivery/wrestler-trellis-native.glb`, 3,862,712 bytes, SHA256
  `2320b27f24ee96fec2eb09db63d431d41641d524b856feb8aff0444b9349b767`.
- Previews: `delivery/wrestler-front-preview.png`,
  `delivery/wrestler-rear-preview.png`, `delivery/wrestler-side-preview.png`.
- Plugin receipt/request/log and server log:
  `hermes-home/plugin-data/remesher/jobs/504de438d27348ef839ca7a5f7b20a43/`.
- Source provenance: `evidence/source-revision.txt`; wheel SHA256
  `ee211089da82c0b5395a2ded162951eb05de1071db39f8af2a46da930fded5b1`.
- JSON reports: `evidence/setup-{plan,check,apply}.json`,
  `plugin-{submit,result,assets,memory,run-summary}.json`,
  `wrestler-{front,rear,side}-glb-inspection.json`, `verification.json`.
- Actual-byte evidence/artifact manifest: `evidence/manifest.json`.
- Reproduction helpers: `prepare_wrestler.py`, `run_plugin_acceptance.py`,
  `render_wrestler.py`, `verify_acceptance.py`. Rerunning generation creates
  another job and requires explicit approved scope configuration first.

The inspected GLB has one mesh/primitive, 72,862 vertices, 77,653 nondegenerate
triangles, finite positions/UVs, valid indices, one PBR material, and embedded
1024-square base-color and metallic/roughness PNGs. Front/rear/side previews
are actual mesh CPU orthographic rasterizations with albedo plus approximate
diffuse light, **not full PBR renders**. They show a recognizable complete
wrestler with no background slabs. Hands are coarse/fused rather than reliable
five-finger anatomy; faceting and scattered texture/seam artifacts remain.
The back is inferred from one view, not ground truth. No rigging, manifold,
watertightness, production topology or quality certification is claimed.

## Setup, isolation and resources

Actual JSON `plan`, `check`, `apply --config` all exited 0; check/apply were
`ready=true`, all four core model hashes verified, zero additional model bytes.
No install/download opt-ins were used. Original five-asset cache was reused;
BiRefNet was only used in explicit input preparation, not silently added to the
CLI graph. Config generation checks readiness again before child startup.

The old runtime overlay depended on ambient user-site torch, so its `python -I`
capability probe correctly failed. Evidence retained as
`setup-check-original-overlay-blocked.json`. A new isolated
`runtime-overlay` venv explicitly references the already installed verified
runtime package directories via a plain `.pth`; no shared/global package was
modified or downloaded. This is operator-prepared dependency reuse, not a
fresh network installation or fully dependency-hash-locked deployment.

Only owned worker scopes received approved normal user-systemd properties:
MemoryMax=64G, MemoryHigh=56G, MemorySwapMax=2G. Effective limits were read back.
Final run wall time was 28.05 seconds, scope peak 5,907,550,208 bytes, minimum
sampled host available RAM 86,776,180,736 bytes, no high/max/OOM events.
These are cgroup RAM measurements, not peak GPU allocation.

Owned child port 38093 was closed afterward; only the acceptance monitor
remained in its scope before exiting. Fish-speech PID 1803186 remained alive,
listening on 18080, with the same 19,363 MiB GPU allocation; final GPU process
list contained no ComfyUI process. Runtime torch's GB10 capability-range
warning remains recorded, but actual inference succeeded. BiRefNet preparation
also emitted a harmless model-patcher destructor warning at process shutdown.

## Tests and review status

- Installed combined wheel full repository/plugin suite: **204 passed plus
  53 subtests, zero skipped/failures/errors**. JUnit records 257 total cases.
  Both native and legacy real CLI HTTP fixture partitions were explicitly
  enabled. These fixture tests are not the GPU evidence above.
- Ruff on plugin code/tests and `git diff --check`: pass.
- Isolated `hermes plugins doctor --ci`: discovery/import/4 registrations pass.
- Isolated `hermes plugins validate --json`: `ok=true`, no warnings.
- TDD: native-config routing, ambiguous settings and configure script failures
  observed before fixes; malformed-schema admission failures observed before
  adding dependency-free schema-v1 inspection. Real installed CLI plan accepts
  the generated private snapshot.
- Independent Codex review passed output isolation/lifecycle wiring and found
  a P2 missing config-structure validation issue. That issue was fixed with
  invalid-document/path/version/overlap regression tests. Its suggestion for
  a native-config-specific timeout HTTP fixture remains additional coverage;
  inherited native-local timeout fixture passes and actual config success
  cleans up the owned child.
- Final independent re-review input preparation hit an approval gate and was
  **not retried or bypassed**. Final re-review is still pending; do not claim
  independent final approval. Initial Codex sandbox filesystem review was
  unavailable, so the initial review used supplied source/diff without tools.

An initial external-cwd full-suite run failed two legacy tests requiring
repository-relative example workflows; rerun from repository cwd with `-I`
and the same isolated installed wheel passed all tests. An initial importlib
pytest collection mode was incompatible with plugin tests' sibling imports;
default test import mode resolved this. Neither was reported as a passing run.

## Remaining gates

- Independent final re-review and normal repository PR review/CI/merge decisions.
- Fresh network installer acceptance, other hardware/platform inference, and
  automatic image background-removal integration are separate work.
- **Pixal3D remains unimplemented/unexecuted in this integration**. No further
  model/download work is implied by this TRELLIS result.
