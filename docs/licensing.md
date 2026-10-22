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
No invented NOTICE is added. The scoped asset update below records the owner's
confirmation and removes one third-party animation from the current tree.

- Native setup points to external ComfyUI and Comfy-Org TRELLIS.2, Pixal3D and
  MoGe repositories; the DINO weight is also an external model artifact.
  Weights and those runtime checkouts are not bundled in the client wheel.
  Inspect the actual pinned upstream terms before downloading or redistributing
  them; model filenames and SPDX metadata here do not establish those rights.
- The Docker recipes obtain separate third-party runtimes/dependencies and may
  package assets not present in the client wheel. A licensed client wheel is
  not blanket clearance of the complete Docker image.

## Scoped demo asset provenance

- `workspace/input/demo/pencil_sketch_character.jpg`, introduced by
  `97c7533ad98cd98837793765316c76416cde56ae`, is preserved unchanged.
  MichaelGold explicitly confirmed in the owner conversation that this is his
  own sketch and that he has the rights to it. This records the supplied owner
  confirmation, rather than inferring authorship from a commit author field.
  The sketch is no longer an unresolved third-party permission gate.
  Copyright ownership confirmation is not an Apache-2.0 grant for the image:
  the code-license decision does not assign a separate blanket asset license,
  or license model weights or generated outputs.
- `workspace/input/animation_templates/mixamo/Mma_Kick.fbx`, introduced by
  `ebf98830b8853c036b313be0181f165b25774d3e`, has been removed from the current
  tree at the owner's request. No redistribution permission is asserted for
  that third-party animation. History has not been rewritten and external
  copies have not been deleted. Historical checkouts may still contain it.
  The notebooks no longer fall back to it or download it: optional retargeting
  requires a user-supplied FBX that the user has rights to use. Without one,
  they keep the rigged GLB for subsequent preview/export.

These two assets no longer constitute the previously identified unresolved
current-tree demo permission gate: one has explicit owner provenance and the
other is no longer bundled. Neither is included in the Python wheel or Hermes
plugin directory. This scoped update is not an exhaustive clearance of other
materials, historical distributions or complete Docker images. Catalog
admission, release approval and final exact-head review remain separate gates.


## Regression evidence

`tests/test_demo_asset_provenance.py` checks that the removed FBX is absent,
executes the notebook retarget cells without an FBX (no subprocess call), checks
explicit missing inputs fail rather than download, and verifies upload-without-FBX
clears a previous selection. The sketch is retained.

`tests/test_release_ci.py` checks SPDX metadata, official license bytes, the
standalone plugin copy and Docker build-context inclusion. The isolated wheel
harness verifies installed `License-Expression`, `License-File` and the exact
`site-packages/*.dist-info/licenses/LICENSE` bytes, without source-import
fallback. CI repeats that check on the exact PR head.
