# Native integration release task index

This is the current delivery index. Historical acceptance reports preserve their
original source IDs, artifact hashes and quality failures; their old branch/review
status is not the current merge queue. Install one integrated revision using
[native installation](native-installation.md), not a stack of feature PRs.

## Source and reconciliation

- Authoritative main at consolidation: `30f1a95ca62935d0a6cb9d3b01c7b51b0a65f8aa`.
- Integrated source tip: `1356297d1977f079d008cb285d275171854bb8cc`.
- Fetched all source PR heads. Both original native and Hermes branches are
  ancestors of the combined source; the subsequent no-decimation, repair,
  Pixal3D/MoGe, cancellation/deadline, 1536 and repair768/atlas4096 stages are
  ancestors of that tip. Main is its ancestor: no conflicting main changes were
  overwritten. Existing worktrees/branches and local acceptance assets preserved.
- Application source, native manifest/inventory and plugin runtime remain
  byte-identical to the integrated source tip. Delivery additions are CI,
  verification scripts, tests and documentation; compatibility defaults unchanged.

## Gates (updated independently; one green row does not imply another)

| Boundary | Implemented | Verification / outstanding gate |
|---|---|---|
| Native TRELLIS.2 and Pixal3D graphs, model setup and MoGe selection | Yes | Existing full CPU suite + separate historical Spark evidence below |
| Per-job setup snapshots, model paths and plugin storage isolation | Yes | Real installed CLI/plugin HTTP/process contracts; no source import fallback |
| No-decimation, portable repair, 1536 cascade, repair768/atlas4096 | Yes | Existing graph/CLI/plugin tests and controlled historical experiments |
| Setup child cancellation and absolute artifact deadline | Yes | Real subprocess cancellation + trickling HTTP regressions |
| Canonical hosted CPU CI | Yes | `.github/workflows/ci.yml`: exact-head remote conclusion required before merge; never infer it from local results |
| Focused lint | Yes | Fatal correctness on all first-party source/tests/scripts; all Pyflakes rules on native/plugin/new delivery code; no inherited diagnostic suppression |
| Full test and isolated wheel partitions | Yes | Local full suite **270 passed + 53 subtests, zero skips**; isolated wheel **219 application + 51 plugin tests + 53 subtests, zero skips**. Four release guards were observed failing before CI/script changes. Required skips fail the gate |
| Hermes SDK doctor and validator | Yes | Immutable SDK `9e01b44dd23978f9ff40b7837467f3a9f1582130`; real discovery registers four tools, catalog validator passes; missing dependencies are errors |
| Clean client installation | Yes | Wheel into independent venv, fresh dependencies, imports from site-packages, both model plans, complete CPU suite and plugin contracts; no GPU inference inferred |
| Fresh normal-config/plugin Spark acceptance | Separate gate | Parent-owned clean runtime/profile acceptance must bind the tested source/wheel to final application bytes. Reuse official existing weights; no downloads authorized |
| Independent final integration review | Separate gate | Release owner obtains exact-head consolidated review; historical approval limitations are not silently treated as approval |
| Merge / branch protection / old PR disposition | Not performed by integration worker | Release-owner gate after exact-head CI and review |
| Docker / package release / plugin catalog | Not published | Docker dispatch defaults `publish=false`; main push no longer launches publishing. Release owner decides distribution |
| Meshy Hermes reference alignment | Pending research | Parent is checking the shipped Meshy source/catalog/API referenced in the October 22 post `2113139938569179201`. No catalog compatibility claim follows from this plugin's SDK validation. Desktop renderer, animation/gallery UI and messenger 360-degree turntable video are separate follow-up scope, not implemented by this integration |

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
