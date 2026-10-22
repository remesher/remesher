# Clean installed-plugin native canaries

The independent installation worker tested source
`1356297d1977f079d008cb285d275171854bb8cc` from a clean archive. It built and
installed the client wheel with newly resolved dependencies, then used the actual
Hermes Git-subdirectory installer in a disposable `HERMES_HOME`. Real discovery,
four registered tools and the bundled skill were used; no direct-import fake
plugin context. Plan/check/apply reused existing official weights and an approved
runtime, with **no install/download opt-ins**. This is not fresh CUDA provisioning.

Both normal settings files selected `backend: native-local` with separate
schema-v1 `native_config` files, preserving the operator files and snapshotting
only runs/output per job. Real registered generation produced textured GLBs:

| Model | Job ID | GLB SHA256 |
|---|---|---|
| TRELLIS.2 | `3efee22e77514271975ccbc3db106ca0` | `8c3c43ef9e06320c3f89707c57abf8952036c2a538854d7290fb7137e5146502` |
| Pixal3D | `0af20435ccad4754984674b6b8d3fb9c` | `230bc4f162bb1212810e5f468a424fe129d13416b0216d6f7ce66fcf9ae44769` |

Independent readback parsed meshes, UV/materials and embedded textures and
verified hashes. The consolidation worker independently rehashed both final
files and compared application/native/plugin/configure executable source against
the tested revision: **unchanged**. Subsequent plugin changes are manifest/version
metadata and standalone documentation; these receive separate SDK validation.
Do not describe the new whole wheel/commit as byte-identical: wheel README and
metadata can differ even though executable source does not.

These were 512 shape, 1024 atlas, no-decimation, **no repair** routing canaries.
Pixal3D used a fixed camera angle, so this run did not re-execute automatic MoGe
estimation. Historical 1536/repair/atlas and automatic MoGe evidence remains
separate. No anatomy, rendering, manifold or production-quality pass is claimed.

Hardware was Linux ARM64 NVIDIA Spark, pinned ComfyUI
`7a28332047b6af638dc6c7f72ef3481a718769fd`, existing approved acceleration. Each
model used its own 64 GiB max / 56 GiB high / 2 GiB swap transient scope. The
worker verified child PID/port cleanup, inactive scopes and unchanged Fish Speech
PID; no active Hermes profile/packages or global resources were modified.

Detailed receipts, executed graphs, install logs, dependency versions, source and
wheel hashes, model-hash checks and resource measurements are preserved on the
acceptance host at:
`/home/mg/remesher-native-runtime/release-install-acceptance/REPORT.md`,
`provenance.json`, `verification.json`, and model-specific subdirectories.
Large models/GLBs are deliberately not committed. Final source review, canonical
CI, license choice, merge and distribution remain separate release-owner gates.
