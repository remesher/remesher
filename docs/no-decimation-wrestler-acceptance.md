# No-decimation wrestler comparison — October 21, 2026

## Outcome

Fresh native TRELLIS generation and UV/PBR GLB export succeeded with **no
DecimateMesh node and no face/vertex cap**. This is not a mesh-quality fix:
the un-decimated export still has open/nonmanifold connectivity and visible
material artifacts. Do not claim decimation caused the original holes.

Implementation commit: `9860f1924317f7d89467fdb3701d618fcb148eb5`.
Isolated worktree: `/home/mg/src/remesher-no-decimation`.
Base verified live from PR20: `e96b3aa578a9aff99bbdf5d26d0e60cb4a0ac6c7`.
No existing worktree was edited. This historical experiment is included in the
integrated source; it is not a branch installation dependency.

## Reproduction and controls

CLI adds `image-to-glb --no-decimation` for native/native-local only. Hermes
`remesher_generate` accepts `no_decimation: true` and sends no target-face flag.
Legacy rejects the option. Defaults remain compatible.

Actual registered plugin handler, latest built isolated wheel, saved setup
snapshot, owned native ComfyUI child and real model inference were exercised.
Job: `a50164545d0b45ca85a9e5d0f811930f`.
Wheel SHA256: `d0fe2ea4c8fae93202c2b78c1e76de45255b60a81bb3e0ecc8dc836c210b0926`.
Installed CLI/backend source hashes exactly match the implementation commit.
ComfyUI remained clean at `7a28332047b6af638dc6c7f72ef3481a718769fd`.

Both job inputs and the original prepared file have identical SHA256
`daf80e42ee9d9ec1b542be545ff598b906743c4693a95f9812e23df09cfc7b94`.
Unchanged: mesh seed 42, texture seed 43, 512 generation preset, steps 12/20/12,
conditioning, all sampler parameters, 1024 UV/texture size, PEC unwrap with
weld_distance 0.0002 and all texture/PBR export nodes. Normalized graphs from
the exact old/new installed modules differ only by removing DecimateMesh and
linking UnwrapMesh to shape_decode. These graph files are explicitly labeled
**reconstructed**, not captured HTTP requests. Actual request argv, child log,
plugin receipt and actual output bytes are retained. Deterministic bitwise
identity of intermediate GPU samples across separate runs is not asserted.

## Deliverables

Root: `/home/mg/remesher-native-runtime/no-decimation-acceptance/`.

- `delivery/wrestler-trellis-no-decimation.glb`: 33,909,440 bytes;
  SHA256 `f7d956a1b6a151a5cef39dc7576dd9a576399cb2076400732e68c2613066dfcf`.
- Actual mesh previews: `delivery/wrestler-front-preview.png`,
  `delivery/wrestler-rear-preview.png`, `delivery/wrestler-side-preview.png`.
- Texture-free diagnostic: `delivery/wrestler-side-clay.png`.
- `evidence/topology-comparison.json`, `verification.json`, `tests.xml`,
  `plugin-{result,memory,run-summary}.json`, reconstructed graph JSONs and
  per-view GLB inspection JSONs.
- Reproduction helpers: `run_plugin_acceptance.py`, `verify_comparison.py`,
  `measure_topology.py`, `render_wrestler.py`, `render_clay.py`.
- Actual child log and job request under
  `hermes-home/plugin-data/remesher/jobs/a50164545d0b45ca85a9e5d0f811930f/`.

The previous GLB and all previous evidence remain untouched.

## Geometry comparison

Both measured with the same read-only accessor/edge-incidence implementation.
UV-seam positions were welded before edge counts. Exact-coordinate welding,
rounding to 1e-6 and rounding to 1e-5 give identical counts for each asset.

| Measurement | Previous 80k target | No decimation |
|---|---:|---:|
| Exported vertices including UV splits | 72,862 | 884,931 |
| Triangles | 77,653 | 1,218,388 |
| Welded vertices | 43,009 | 608,765 |
| Boundary edges (one incident triangle) | 17,674 | 21,036 |
| Nonmanifold edges (>2 incident triangles) | 3,178 | 17,235 |
| Collapsed triangles after weld | 0 | 0 |
| Duplicate triangles ignoring winding | 11 | 284 |
| Boundary edges after triangle deduplication | 17,683 | 21,059 |
| Nonmanifold edges after deduplication | 3,161 | 16,846 |

The parent's prior rounded-1e-6 counts are reproduced exactly. These are edge
counts, **not numbers of holes**. Duplicate triangles explain some excess
incidence but not most connectivity defects. A KD-tree probe of boundary edges
after triangle deduplication found no collinear interior vertices within 1e-6
in either mesh, so exact T-junctions at that tolerance do not explain these
counts. This is not a proof against near-T-junctions at looser tolerances or
self-intersections. Welding/deduplication/probes are measurement-only; delivered
GLB bytes were not repaired. UV unwrap itself still welds and duplicates
vertices, so this experiment cannot assign defects to shape decoding versus UV
processing. It isolates explicit simplification, not every postprocess stage.

New GLB: one mesh/primitive, 1,218,388 nondegenerate triangles, finite positions
and UVs, valid indices, one PBR material with embedded 1024-square base-color
and metallic/roughness PNGs. Those checks do not imply watertightness.

## Visual assessment

Front/rear/side are actual-GLB orthographic CPU rasterizations using base color
and approximate diffuse light, not full PBR. New geometry looks smoother and
retains finer boot/hair details, but hands remain coarse/fused. Colored speckle,
striping and large gray/dark patches remain, especially thigh, boots and back.
The constant-gray side diagnostic removes much of that colored damage while
showing continuous large-scale thigh/boot surfaces: those patches cannot all
be called geometric holes. Small surface irregularities/open connectivity
remain. Rear anatomy is inferred from one image. This is a provisional quality
result, not production-ready/manifold/rigging acceptance.

## Resources, tests and remaining gates

Only owned `hermes-worker-proc_0f6e341fb56c.scope` received normal user-systemd
MemoryMax=64G, MemoryHigh=56G, MemorySwapMax=2G, read back explicitly. Initial
set-property used a nonexistent terminal-prefixed unit name and failed without
changing any unit; corrected to the discovered owned worker scope before run.
Setup plan/check/apply succeeded; existing approved four core model hashes were
reverified, with no model downloads. Runtime/model environment reused unchanged.
Client wheel dependencies were installed only in the new isolated CLI venv.

Actual prompt execution: 25.94 seconds; plugin wall time: 36.12 seconds.
Scope peak: 5,844,447,232 bytes; minimum sampled host available RAM:
85,173,248,000 bytes; high/max/OOM events all zero. These are RAM/cgroup numbers,
not GPU-allocation peak. Owned port 42697 is closed and ComfyUI exited.
Fish-speech PID 1803186 remains the sole NVIDIA compute process at 19,363 MiB;
listener 18080 remains. No shared service, active Hermes config or cloud resource
was changed. Pixal3D was not run or downloaded.

TDD RED failures were observed for graph bypass, CLI routing/legacy rejection
and plugin forwarding/validation, then GREEN. Clean implementation commit with
installed wheel: **209 passed plus 53 subtests, zero skipped/failures/errors**;
JUnit is retained. Both installed-CLI HTTP fixture partitions enabled; these
protocol tests are separate from the real GPU evidence above. Scoped Ruff and
git diff --check pass. Full source-file lint was not newly certified.

Known runtime GB10/PyTorch capability warning and deprecated disable-api-nodes
warning remain in logs; actual inference succeeded. Independent final code
review and remote CI are separate remaining gates. No merge authorized.
