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

These are documented recipes, **not new `--preset` flags**. Runtime config owns
model/paths/device; generation arguments own quality. Higher settings can cost
more memory/time and do not necessarily produce a better mesh.

| Recipe | Model selection | Shape | Simplification | Repair | UV/PBR atlas |
|---|---|---:|---|---|---:|
| Compatibility native | config `model: trellis2` or `pixal3d` | 512 | existing 80000 face target | none | 1024 |
| Recommended uncapped baseline | either model, separately verified | 512 | `--no-decimation` | `--mesh-repair solid --repair-resolution 512` | 1024 |
| Detail experiment | Pixal3D tested; TRELLIS needs separate acceptance | `--native-shape-resolution 1536` | `--no-decimation` | `--mesh-repair solid --repair-resolution 768` | `--native-atlas-resolution 4096` |

The recommended baseline avoids a global face/vertex cap; solid repair can still
change topology. No hidden vertex limits are introduced. Use `--mesh-repair none`
for raw-decode/UV diagnostics. Only shape 512/1536 and atlas 1024/4096 are accepted.
1536 adds the 12-step Euler/simple shape cascade; repair grid and atlas remain
independent. Pixal3D estimates horizontal FoV with MoGe by default; a diagnostic
`--native-camera-angle` freezes it. TRELLIS does not use MoGe. See the
[cascade](native-shape-cascade.md) and [repair/atlas evidence](native-repair-atlas.md).

```sh
"$CLI" image-to-glb --backend native-local \
  --native-config /absolute/trellis-runtime/native-setup.json \
  --image /absolute/prepared.png --mesh-seed 42 --texture-seed 43 \
  --no-decimation --mesh-repair solid --repair-resolution 512
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
`image`, `no_decimation: true`, `mesh_repair: solid`, `repair_resolution: 512`.
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
