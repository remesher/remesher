# License scope and distribution checks

The owner selected **Apache-2.0 for Remesher's own code**. The root `LICENSE`
and `integrations/hermes/LICENSE` are byte-identical copies of the official
Apache License 2.0 text from https://www.apache.org/licenses/LICENSE-2.0.txt
(SHA-256 `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`).
The Python package declares `license = "Apache-2.0"` and ships `LICENSE` in its
wheel; the standalone Hermes plugin also bundles the full license.

## Scope, not a blanket grant

This decision does not relicense third-party code, dependencies, external
runtimes, model weights, input assets or generated outputs. Their respective
terms and any applicable notices remain controlling. Keep upstream license,
copyright and NOTICE files when separately obtaining or distributing upstream
materials; this repository's license is not a substitute for them.

A future proprietary managed fstack-remesher service is a separate product
boundary, not an exception that retracts this grant for the released Remesher
code. No hosted implementation is added or licensed by this change.

## Scoped repository inspection

The licensing change inspected tracked source, integration and worker scripts,
example/notebook references, the native setup manifest, Docker packaging paths,
license/notice/attribution markers and the history of bundled demo assets. This
is not an exhaustive provenance audit or legal review. No pre-existing tracked
LICENSE/NOTICE file or explicit copied-source attribution was found in this
inspection; that is not proof that all code has independently verified origin.
No invented NOTICE is added. Existing source, assets and upstream references
are preserved unchanged.

- Native setup points to external ComfyUI and Comfy-Org TRELLIS.2, Pixal3D and
  MoGe repositories; the DINO weight is also an external model artifact.
  Weights and those runtime checkouts are not bundled in the client wheel.
  Inspect the actual pinned upstream terms before downloading or redistributing
  them; model filenames and SPDX metadata here do not establish those rights.
- The Docker recipes obtain separate third-party runtimes/dependencies and may
  package assets not present in the client wheel. A licensed client wheel is
  not blanket clearance of the complete Docker image.
- `workspace/input/animation_templates/mixamo/Mma_Kick.fbx` is a tracked Mixamo
  animation, introduced by `ebf98830b8853c036b313be0181f165b25774d3e`.
  No redistribution permission record accompanies it in this repository.
- `workspace/input/demo/pencil_sketch_character.jpg` is a tracked demo image,
  introduced by `97c7533ad98cd98837793765316c76416cde56ae`.
  Its authorship and redistribution permission are not established by the
  commit's author field or by the code license.

**Outstanding distribution gate:** the owner must establish permission for
those bundled demo assets, or separately remove/replace them before source/demo
redistribution. They are excluded from this first-party code license grant and
are not included in the Python wheel or Hermes plugin directory. This change
neither deletes assets nor claims their redistribution is authorized. Catalog
admission, release approval and final exact-head review remain separate gates.

## Regression evidence

`tests/test_release_ci.py` checks SPDX metadata, official license bytes, the
standalone plugin copy and Docker build-context inclusion. The isolated wheel
harness verifies installed `License-Expression`, `License-File` and the exact
`site-packages/*.dist-info/licenses/LICENSE` bytes, without source-import
fallback. CI repeats that check on the exact PR head.
