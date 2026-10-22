# Native installation and agent operation

This integrated source includes native TRELLIS.2, native Pixal3D and the Hermes
plugin. Do not assemble historical feature branches. The compatibility default
is still `comfy3d`; select native explicitly. Native inference has been exercised
on **Linux ARM64 / NVIDIA DGX Spark** only. CPU protocol CI is not certification
of macOS, Windows, MPS, ROCm or CPU inference. The client requires Python 3.11+;
the pinned native runtime and plugin require POSIX. No production/manifold,
watertight, printable, anatomy or uniformly better texture guarantee is made.

## Install the client separately

From this repository at the release/integration revision you intend to test:

```sh
uv build --wheel
uv venv /absolute/remesher-client --python 3.13
uv pip install --python /absolute/remesher-client/bin/python dist/*.whl
/absolute/remesher-client/bin/comfy-prompt-cli --help
```

Do not install ComfyUI/Torch into the client or Hermes environment. Native graph,
manifest and setup code ship in the wheel. Legacy workflow JSON is intentionally
external: retain `examples/` from the same revision and configure its absolute
path when using Comfy3D. The native graph needs no example workflow file.

## Prepare a native runtime with explicit approval

```sh
CLI=/absolute/remesher-client/bin/comfy-prompt-cli
# Read-only: review paths, pinned sources, bytes, memory and model requirements.
"$CLI" native-setup plan --root /absolute/trellis-runtime --model trellis2
"$CLI" native-setup plan --root /absolute/pixal-runtime --model pixal3d
# Only after approval for package installation AND the reported download bytes:
"$CLI" native-setup apply --root /absolute/trellis-runtime --model trellis2 \
  --allow-install --allow-download
```

For existing verified weights, instead save the plan's **config object** with
`schema_version: 1`, `model: trellis2` or `pixal3d`, and absolute `venv`,
`checkout`, `models`, `runs`, `output` paths. Reuse approved runtime/weights and
use separate config/run/output paths for each model. Run `plan`, `check` and
`apply --config /absolute/native-setup.json` **without either opt-in**. Apply
only publishes a ready config; missing assets/dependencies fail, never download
silently. Pixal3D needs its own diffusion model and MoGe in addition to shared
VAE/DINO weights. See [setup schema and resource policy](native-setup.md).
Check/apply must exit zero and report `ready: true`; health alone is insufficient.

Input must be an already masked, square, black-background composite. Preserve
original/mask/prepared input; neither plugin nor CLI removes backgrounds.
Protect hands/feet with margins. Camera and cropping can dominate quality.

## Explicit presets: labels map to real controls, not hidden defaults

Select `--native-preset quality-1536-solid768` for the tested single-image
quality recipe on either model. This is an explicit, expensive opt-in, not a
silent change to existing invocations. Runtime config owns model/paths/device;
generation arguments own quality. Higher settings cost more memory/time and
do not guarantee better anatomy or textures.

| Recipe | Model selection | Shape | Simplification | Repair | UV/PBR atlas |
|---|---|---:|---|---|---:|
| Compatibility native / `--native-preset fast` | either model | 512 | 80000 face target | none | 1024 |
| Recommended `--native-preset quality-1536-solid768` | either model, separately exercised | 1536 | no decimation | solid768 + bounded fill | 4096 |

Quality resolves to shape1536, solid repair768, atlas4096, no decimation,
precluster_max_verts=0, fix_poles=false, smooth_iters=0, component threshold0.005,
hole perimeter0.03, max_vertices16 **per hole**, fill_chains=false and no pre-weld.
All native exports now attach explicit smooth normals at 180 degrees after
material application; positions, indices, UVs and materials are not changed by
that node. No tangents are needed without a normal map. Repair/unwrap still
change geometry; this is not a manifold guarantee.

Omitting the preset retains the historical CLI values. With a preset, matching
explicit controls are accepted; contradictions (including any face target with
quality) fail before upload/startup. For custom combinations omit the preset.
Seeds, model and camera remain independent. The CLI prints resolved values.
See [normal export and preset verification](native-quality-normals.md).
1536 adds the 12-step Euler/simple shape cascade; repair grid and atlas remain
independent. Pixal3D estimates horizontal FoV with MoGe by default; a diagnostic
`--native-camera-angle` freezes it. TRELLIS does not use MoGe. See the
[cascade](native-shape-cascade.md) and [repair/atlas evidence](native-repair-atlas.md).

```sh
"$CLI" image-to-glb --backend native-local \
  --native-config /absolute/trellis-runtime/native-setup.json \
  --image /absolute/prepared.png --mesh-seed 42 --texture-seed 43 \
  --native-preset quality-1536-solid768
# For Pixal3D, select the separate config with model=pixal3d; do not pass a
# conflicting --native-model alongside an authoritative native config.
```

## Install and configure the Hermes plugin

Validate the entire plugin directory using your installed Hermes SDK:

```sh
hermes plugins doctor /absolute/remesher/integrations/hermes --ci
hermes plugins validate /absolute/remesher/integrations/hermes --json
```

With authorization, use the tested Git-subdirectory installer with the exact
reviewed integration/release SHA, in the intended home:

```sh
: "${REMESHER_REVISION:?Set the approved full 40-character commit SHA}"
HERMES_HOME=/absolute/disposable-hermes hermes plugins install \
  remesher/remesher/integrations/hermes --ref "$REMESHER_REVISION" --yes-deps --enable
```

This is a custom-source install, not catalog admission. It includes the scripts
and skills; start a fresh session in that home. For evaluation use a new
disposable directory; do not mutate your active profile or its Python packages.
Hermes 0.22.2 is the validated SDK floor. Remesher code is licensed
Apache-2.0 by owner decision; third-party materials retain their terms. See the bundled
[catalog preparation notes](../integrations/hermes/CATALOG.md).

Publish settings with the bundled configuration script:

```json
{
  "cli": "/absolute/remesher-client/bin/comfy-prompt-cli",
  "backend": "native-local",
  "native_preset": "quality-1536-solid768",
  "native_config": "/absolute/trellis-runtime/native-setup.json"
}
```

```sh
python /absolute/remesher/integrations/hermes/scripts/configure.py \
  --input /absolute/candidate-settings.json \
  --output /absolute/private/remesher-settings.json
export REMESHER_SETTINGS=/absolute/private/remesher-settings.json
```

In that new Hermes session use `remesher_health`, then `remesher_generate` with
`image`; the explicitly configured quality preset supplies the tested values.
Request `native_preset: fast` for a bounded smoke instead. Request preset takes
precedence over settings preset; request scalar controls take precedence over
settings scalar controls, but all must agree with the selected preset. Settings
JSON is authoritative over environment; the scalar alternative is
`REMESHER_NATIVE_PRESET=quality-1536-solid768`. No preset means old behavior.
Poll `remesher_job`, retrieve `remesher_assets` and verify its hashes. To select
Pixal3D, publish a separate settings file pointing to its separate setup config.
The plugin snapshots config per job and owns only its own children; a timeout
against an operator-managed server does not cancel remote work. Inspect logs and
mesh renders before quality acceptance. See [complete plugin contract](../integrations/hermes/README.md).

## Release gates

[Release task index](release-readiness.md) separates implementation, exact-head
CPU CI, clean installation, historical/live Spark inference and independent
review. Docker publication is manual, defaults off, and is not a merge side
effect. Do not run a release until the release owner approves the remaining gates.
