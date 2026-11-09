# Remesher project plan

## Direction and scope

Remesher's confirmed direction is native 3D generation and rigging, integration
with Hermes, and eventual paid cloud execution through Fstack. Native generation
already has implemented paths; this direction does not imply that native rigging,
all-platform support or a paid hosted service is complete.

This is the whole-project scope and planning index. The
[technical release-readiness index](docs/release-readiness.md) continues to own
its detailed delivery gates and links to historical acceptance receipts. Do not
rewrite those receipts to make earlier source IDs, test results or quality
failures look current. Use [installation](docs/native-installation.md), the
[CLI guide](README.md) and [Hermes integration](integrations/hermes/README.md)
for operational contracts rather than treating this plan as installation advice.

## Component boundaries

| Component | Role |
|---|---|
| [remesher/remesher](https://github.com/remesher/remesher) | Primary CLI, native execution integration, Hermes plugin, workflows and technical acceptance documentation; this repository owns the whole-project plan. |
| [ComfyUI-UniRig fork](https://github.com/michaelgold/ComfyUI-UniRig) | Remesher rigging component; distinguish maintained fork work from upstream dependency activity. |
| [ComfyUI-GeometryPack fork](https://github.com/michaelgold/ComfyUI-GeometryPack) | Remesher geometry component; distinguish maintained fork work from upstream dependency activity. |
| [ComfyUI-Blender-Nodes](https://github.com/michaelgold/ComfyUI-Blender-Nodes) | Remesher Blender workflow component. |
| remesher.com website | Product website component, not evidence that a hosted execution service is available. |

Comfy3D is a separate maintenance/compatibility project, not a Remesher component.
Its existing runtime remains supported by the current CLI; new Remesher product
direction does not silently change that default. Fstack is the planned cloud
execution integration boundary, not a currently certified Remesher service.
The specific upstream Hermes catalog contribution belongs to Remesher's
integration history; unrelated upstream Hermes activity does not.

## Reconciled implementation snapshot

Snapshot inspected at default-branch commit
`d563b5f214d276d49d4d37780e36f24db00abe79`. These are source and recorded acceptance
facts, not a new hardware test or a declaration of release/deployment readiness.

- **Native generation implemented, quality bounded.** Native TRELLIS.2 and
  Pixal3D integration, setup controls, owned local runtime lifecycle and explicit
  quality presets are on main. [PR #27](https://github.com/remesher/remesher/pull/27)
  merged the integrated native/Hermes work. Historical Spark runs and remaining
  visual defects are linked from the technical index; CPU tests do not establish
  GPU inference, anatomical quality or production-manifold output.
- **Hermes integration implemented.** The plugin wraps an isolated CLI and
  exposes explicit setup/generation contracts. The pinned plugin catalog
  contribution [upstream PR #143074](https://github.com/NousResearch/hermes-agent/pull/143074)
  was merged. Catalog acceptance is not adoption, deployment, billing acceptance
  or proof that every newer repository revision is the catalog's pinned version.
- **macOS support has separate evidence boundaries.**
  [PR #28](https://github.com/remesher/remesher/pull/28) added prepared-runtime MPS
  support, and [PR #29](https://github.com/remesher/remesher/pull/29) added explicit
  provisioning. A prepared-runtime plugin run completed; fresh provisioning,
  model reuse and MPS readiness passed, but generation on the freshly provisioned
  runtime timed out before returning a final textured asset. See
  [macOS provisioning acceptance](docs/macos-provisioning-acceptance.md).
  Do not substitute the earlier successful run for that incomplete run or infer
  macOS rigging parity from provisioning success.
- **Existing rigging is not universal native-rigging acceptance.** The current
  CLI documents MIA rigging with an isolated Blender automatic-weight post-stage
  and a preserved raw-MIA opt-out. Rigging, cleanup, retargeting and exports need
  their own structural, deformation and visual evidence. A generated skeleton,
  nonzero weights or a moving animation alone is insufficient. Experimental
  comparisons and unmerged local corrections are not new defaults.
- **SkinTokens remains unmerged.** At this snapshot,
  [PR #30](https://github.com/remesher/remesher/pull/30) is a draft optional-backend
  change, not an accepted default or a completed product milestone.
- **Paid cloud execution remains planned.** No claim of implemented Remesher
  billing, hosted authentication, tenant isolation or cloud runtime acceptance
  follows from the native CLI or plugin work.

The older release-readiness rows saying merge was not performed, plugin catalog
was not published, and no MPS inference was claimed describe their earlier
integration boundary. The merged PRs and later macOS acceptance above reconcile
those points without changing historical receipts. Other distribution and
hardware claims still require their own evidence; this reconciliation does not
clear every release gate.

## Plan and acceptance boundaries

1. **Maintain and qualify native generation.** Preserve explicit setup/download
   permissions, reproducible runtime configuration, lifecycle cleanup and
   artifact validation. Bind acceptance to the actual source, runtime, model and
   exported asset. Keep CPU contract checks, real inference, visual quality and
   distribution as separate gates; use the technical index for detailed work.
2. **Advance native rigging toward the confirmed product goal.** Preserve the
   working compatibility path while candidates are evaluated. Require texture/UV
   retention, coherent skeletons, finite normalized weights, fresh artifact
   reimport and representative deformation/render checks. Backend selection and
   promotion must follow evidence, not merely an adapter or passing fixture.
   This plan does not approve a new backend/default or mark experimental fixes
   as delivered.
3. **Maintain Hermes access to verified capabilities.** Keep plugin/CLI contracts,
   explicit execution permissions and isolated dependencies aligned. Validate the
   installed plugin and actual output path for each claimed capability; do not
   infer rigging support from image-to-GLB catalog acceptance. Desktop viewer or
   gallery integration remains separately owned, and messenger previews are not
   a Remesher release obligation.
4. **Plan paid execution through Fstack separately.** This is confirmed direction,
   not an implementation or deployment authorization. Before claiming service
   readiness, a separately reviewed integration must establish authenticated,
   isolated execution, job/artifact lifecycle and paid-execution behavior.
   Provider, infrastructure, pricing, launch date and detailed service contract
   remain undecided here; no speculative API or commercial commitment is added.

## Cross-cutting limits

- Preserve the existing multi-repository product boundary; component publication
  is not whole-product completion.
- First-party code is Apache-2.0. Model weights, dependencies, input assets and
  generated outputs have separate rights and distribution checks; see
  [licensing](docs/licensing.md).
- Require normal reviewed PRs and required exact-head checks for changes. A
  documentation update does not require new model generation or imply a release.
- Keep unresolved quality, platform and release gates explicit. No inference
  speed, universal rig quality, new hardware certification or paid-cloud
  availability is promised by this plan.
