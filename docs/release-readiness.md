# Native integration release task index

This is the current delivery index. Historical acceptance reports preserve their
original source IDs, artifact hashes and quality failures; their old branch/review
status is not the current merge queue. Install one integrated revision using
[native installation](native-installation.md), not a stack of feature PRs.

## Source and reconciliation

- Final premerge normals/preset delta is described in
  [native quality and explicit normals](native-quality-normals.md). It adds the
  named `quality-1536-solid768` opt-in and smooth exported NORMAL, preserving
  legacy invocation defaults. Recommended native agent configuration selects
  quality explicitly. This supersedes recipe-only/512 baseline guidance, not
  the historical source IDs below. Both saved final wrestler meshes were
  re-exported on CPU with unchanged positions/indices/UVs/materials; no new
  full model generation or reference-parity claim is made.

- Authoritative main at consolidation: `30f1a95ca62935d0a6cb9d3b01c7b51b0a65f8aa`.
- Integrated source tip: `1356297d1977f079d008cb285d275171854bb8cc`.
- Fetched all source PR heads. Both original native and Hermes branches are
  ancestors of the combined source; the subsequent no-decimation, repair,
  Pixal3D/MoGe, cancellation/deadline, 1536 and repair768/atlas4096 stages are
  ancestors of that tip. Main is its ancestor: no conflicting main changes were
  overwritten. Existing worktrees/branches and local acceptance assets preserved.
- The original consolidation preserved application source, native manifests and
  plugin runtime. Subsequent bounded delivery fixes cover setup cancellation,
  artifact deadlines and the runtime spawn/SIGTERM window; executable source is
  no longer byte-identical to that historical tip. Both model/backends and
  compatibility defaults remain covered by the complete tests.
- Final bounded CPU/review evidence is in [PR27 validation](pr27-final-validation.md).
  Fresh GPU acceptance and exact-head hosted CI are separate gates.

## Gates (updated independently; one green row does not imply another)

| Boundary | Implemented | Verification / outstanding gate |
|---|---|---|
| Native TRELLIS.2 and Pixal3D graphs, model setup and MoGe selection | Yes | Existing full CPU suite + separate historical Spark evidence below |
| Per-job setup snapshots, model paths and plugin storage isolation | Yes | Real installed CLI/plugin HTTP/process contracts; no source import fallback |
| No-decimation, portable repair, 1536 cascade, repair768/atlas4096 | Yes | Existing graph/CLI/plugin tests and controlled historical experiments |
| Named quality/fast presets and explicit final NORMAL | Yes | Actual fixed-mesh CPU native exporter regressions on both accepted final GLBs; finite unit normals, exact geometry/UV/material preservation; CLI/plugin conflict/precedence tests. See [evidence](native-quality-normals.md). Final exact-head CI/review remains a gate |
| Setup child cancellation and absolute artifact deadline | Yes | Real subprocess cancellation + trickling HTTP regressions |
| Canonical hosted CPU CI | Yes | `.github/workflows/ci.yml`: exact-head remote conclusion required before merge; never infer it from local results |
| Focused lint | Yes | Fatal correctness on all first-party source/tests/scripts; all Pyflakes rules on native/plugin/new delivery code; no inherited diagnostic suppression |
| Full test and isolated wheel partitions | Yes | Normals/preset candidate: local **306 passed + 57 subtests, zero skips**; isolated wheel **253 application + 53 plugin tests + 57 subtests, zero skips**. License/packaging guards remain included. Required skips fail the gate; hosted exact-head conclusions are separate |
| Hermes SDK doctor and validator | Yes | Official v0.22.2 floor `d923a5eb487a17c0a68801bba9ef0f56c81040a8` and installed SDK `9e01b44dd23978f9ff40b7837467f3a9f1582130` passed; CI pins the floor and uses the upstream install-stamp writer for version admission. Real discovery registers four tools, validator passes; missing dependencies are errors |
| Clean client installation | Yes | Wheel into independent venv, fresh dependencies, imports from site-packages, both model plans, complete CPU suite and plugin contracts; no GPU inference inferred |
| Fresh normal-config/plugin Spark acceptance | Separate final-source gate | Earlier independent clean archive/client and real Hermes install passed both-model 512/no-repair canaries with existing official weights; [historical scope and receipts](clean-install-acceptance.md). Subsequent lifecycle fixes change executable source: the parallel GPU acceptance owner must bind new receipts to that source. Not fresh CUDA provisioning or 1536 quality |
| Independent final integration review | Bounded delta reviewed | Independent non-author inspection of `8a034ab` through `f827138` found no blocking integration regression, with both original P2 reproductions rerun; [review and limitations](pr27-final-validation.md). Codex sandbox was unavailable, not an approval. Release owner combines this with prior baseline review and final exact-head CI |
| Merge / branch protection / old PR disposition | Not performed by integration worker | Release-owner gate after exact-head CI and review |
| Docker / package release / plugin catalog | Not published | Docker dispatch defaults `publish=false`; main push no longer launches publishing. Release owner decides distribution |
| Meshy reference alignment | Packaging only, verified | Kept Python manifest/four-tool ABI; quoted 0.2.1 version, validated Hermes 0.22.2 floor, Linux metadata, owner-approved Apache-2.0 code license and pinned external documentation. See `integrations/hermes/CATALOG.md`. No MCP rewrite or catalog admission claim |
| First-party code license | Resolved by owner | Apache-2.0 in root/package/plugin metadata; exact full text ships in wheel and plugin. Does not license weights or third-party materials |
| Third-party redistribution | Scoped demo gate resolved; broader scope separate | MichaelGold confirmed sketch ownership/rights; Mixamo FBX removed from current tree. No blanket asset/model license or historical clearance; see [scoped inspection](licensing.md). Not an exhaustive legal review |
| Desktop viewer/gallery | External ownership | Teknium will integrate this; not a Remesher implementation obligation or release gate. Messenger previews are out of scope |
| Future hosted service | Product plan only | Paid managed fstack-remesher is future work; no billing/auth/hosted runtime or speculative API added |

## Canonical commands and contexts

```sh
uv sync --frozen
uv pip install --python .venv/bin/python pytest==9.1.1 pytest-subtests==0.15.0
REMESHER_TEST_CLI="$PWD/.venv/bin/comfy-prompt-cli" \
REMESHER_TEST_NATIVE_CLI="$PWD/.venv/bin/comfy-prompt-cli" \
  .venv/bin/python -m pytest -q tests integrations/hermes/tests --junitxml=reports/tests.xml
.venv/bin/python scripts/verify-test-report.py reports/tests.xml
sh scripts/verify-native-wheel.sh
```

Required contexts to consider for main protection: `Focused lint`,
`CPU tests (Python 3.11)`, `CPU tests (Python 3.13)`,
`Isolated wheel contracts`, `Hermes SDK doctor and validator`.
CI runs hosted Ubuntu CPU fixtures only, never model inference or GPU downloads.
The SDK job checks out the pinned upstream revision separately and installs only
its lightweight validation dependencies. It does not mutate any live Hermes home.
First hosted execution exposed two runner assumptions: absent `$HOME/.cache`
and Rich forcing ANSI formatting under `GITHUB_ACTIONS`. The wheel harness now
creates its scratch parent (preferring `TMPDIR`/`RUNNER_TEMP`), preserves JUnit
on failure, and CI uses plain terminal output (`TERM=dumb`, `NO_COLOR=1`). Both
failures were reproduced and the complete local partitions rerun successfully;
no tests were skipped or assertions weakened. Exact-head hosted rerun remains
the authoritative CI gate.

## Actual historical hardware evidence (not fresh exact-head claims)

- [TRELLIS plugin → installed wheel → owned native runtime](trellis-plugin-acceptance.md).
- [No-decimation](no-decimation-wrestler-acceptance.md) and
  [portable repair](portable-repair-wrestler-acceptance.md).
- [Pixal3D with MoGe](pixal3d-acceptance.md): pipeline succeeded, initial hands
  failed visual quality; padding/camera experiments are asset-specific.
- [1536 cascade](pixal1536-acceptance.md) and
  [repair768 / atlas4096](native-repair-atlas.md): more detail, still fused/coarse
  hands, inferred-back texture defects and nonmanifold edges.

Verified hardware scope is Linux ARM64 NVIDIA Spark with its existing approved
acceleration stack. No macOS/Windows/MPS/ROCm/CPU inference or production manifold
claim. Large GLBs, weights, model packages and generated previews remain outside Git.
