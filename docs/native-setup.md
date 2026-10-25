# Agent-operated native setup contract

The legacy backend remains the default. Optional setup supports explicit
`trellis2` (default, four weights) and `pixal3d` (five weights) presets.
Pixal3D reuses the identical hashed shape VAE, texture VAE and DINO assets;
only its diffusion model and MoGe geometry model are additional downloads.
BiRefNet is not included: both paths consume an already prepared image.
See [Pixal3D acceptance](pixal3d-acceptance.md): pipeline execution passed,
but this wrestler's elongated hands **failed visual quality**.

## Executable interface (also for the Hermes plugin)

```sh
# No writes, installs, downloads or GPU probe. stdout is one JSON document.
comfy-prompt-cli native-setup plan --root /absolute/native-runtime

# Explicit alternate preset; --model is accepted only with --root.
comfy-prompt-cli native-setup plan --root /absolute/pixal-runtime --model pixal3d

# Inspect existing resources; no installs/downloads/server launch.
comfy-prompt-cli native-setup check --config /absolute/native-setup.json

# Only after approval for BOTH packages and the stated model download bytes:
comfy-prompt-cli native-setup apply --root /absolute/native-runtime \
  --allow-install --allow-download

# apply saves root/native-setup.json only once checks pass.
comfy-prompt-cli image-to-glb --backend native-local \
  --native-config /absolute/native-runtime/native-setup.json \
  --image /absolute/prepared-object.png --mesh-seed 42 --texture-seed 43 \
  --native-preset quality-1536-solid768
```

`python -m comfy_prompt_cli.native_setup` is the identical setup interface.
The generation example explicitly selects the more expensive tested quality
recipe; use `--native-preset fast` for a smoke. Setup does not silently change
generation defaults. See [preset controls and precedence](native-installation.md).
`native-setup --help` prints CLI usage. Use `--root` **or** `--config`, not both.
A plugin should invoke argv directly, parse JSON stdout, and branch on exit code:

* **0**: plan produced, or check/apply `ready=true`.
* **1**: check/apply has `ready=false`; inspect `blockers`, `memory`, `capabilities`,
  `checkout`, and per-model `status`/`verified`. Do not launch inference.
* **2**: invalid arguments/configuration, failed operation, or transport error;
  JSON contains `ok=false` and `error`. Installer details go to the dedicated
  venv's `native-setup.log`, not mixed into JSON stdout.

`generation_validated` is always false. Setup readiness is a prerequisite, NOT
proof of successful model execution, GPU support, geometry, or texture quality.
The probe imports runtime dependencies and queries CUDA availability/device
properties. With `device=mps`, it also creates an MPS tensor, multiplies it,
synchronizes and checks the numeric result; availability alone is insufficient.
This is not inference or a performance benchmark. Calls have bounded
subprocess/network timeouts; model download deadlines are per file, with up to
30 seconds of in-flight socket timeout beyond the deadline.

Installer commands are owned process groups. On SIGTERM, the main-thread runner
unwinds with exit status 143, sends TERM to its own group, waits at most five
seconds, escalates to KILL (including remaining descendants), and waits at most
five more seconds to reap its direct child. Repeated SIGTERM is ignored during
cleanup, and the caller's previous handler is restored afterward, including on
spawn failure. SIGKILL and host failure cannot run this cleanup. No unrelated
process or existing server is terminated.

### Configure arbitrary existing paths

Save the `config` object from plan, not the entire report, as JSON. For example:

```json
{
  "schema_version": 1,
  "venv": "/absolute/python-env",
  "checkout": "/absolute/ComfyUI",
  "models": "/absolute/model-cache",
  "runs": "/absolute/private-runs",
  "output": "/absolute/exported-meshes",
  "device": "cuda",
  "minimum_memory_gib": 32
}
```

All five paths must be absolute, distinct, non-root, without `..`; the venv must
not overlap other paths. Unsupported keys, devices, and schema versions fail
closed. Automated installation supports Linux and Apple Silicon macOS (see below). `cpu` is an
experimental runtime choice, not an inference-certified fallback. Existing
venvs (including operator-prepared overlays) can be checked and reused, but the
installer never adopts/modifies an unmanaged venv. If dependencies are missing,
choose a new venv path or repair that environment separately.

The config supplies interpreter (`venv/bin/python`), checkout, model root, private
run root, output directory, and device policy. Conflicting explicit runtime path,
device, or `--out-dir` flags are rejected rather than silently overriding config.
Seeds, face count, timeout, port, and startup timeout remain normal generation
options. Config mode derives its model from the saved config and rejects a
conflicting explicit `--native-model`.

Before config-based generation, all hashes, checkout identity, capabilities and
memory are checked again. The launcher writes a private JSON-as-YAML
`models.yaml` and passes `--extra-model-paths-config` to the owned process, with
configured diffusion/vision/VAE directories first in model search order. No
symlink/copy into ComfyUI is needed. The existing explicit launcher flags remain
available; `--native-models /absolute/cache` provides the same model visibility
without a setup config. Those manual flags do not imply setup verification.

### Approval, isolation, and resources

* `plan` is read-only. `check` reads/hashes local files and runs the explicitly
  configured venv probe (45-second timeout); it does not install anything.
* `apply` without opt-ins only checks/reuses existing resources and saves the
  config if ready. Install and model download approvals are independent and are
  never persisted in config. With missing resources, use only the necessary
  opt-in. No hidden background downloads occur during generation.
* The installer fetches only Comfy-Org/ComfyUI revision
  `7a28332047b6af638dc6c7f72ef3481a718769fd`; it verifies clean tracked content and
  the pinned requirements SHA256. It never resets an existing incompatible tree.
  New venvs do not inherit system site packages. On Linux, Torch 2.10.0, torchvision 0.25.0
  and torchaudio 2.10.0 use the official CPU or cu130 wheel index, then constrained
  ComfyUI requirements use PyPI. macOS uses the separate pinned policy below.
  Only binary distributions are accepted. The
  complete transitive Python environment is **not hash-locked**; dependency
  resolver/wheel availability can still fail, explicitly, without global Python
  or torch mutation. No arbitrary install URL, script, model manifest or revision
  override is exposed by the CLI. Install subprocesses use argv, not a shell.
* Models use packaged official repository revisions, exact sizes and SHA256.
  Files are streamed, atomically promoted only after verification, and rehashed
  before reuse. `.part` files resume with validated Range responses; servers
  ignoring Range restart safely. Corrupt final files are never overwritten:
  move them aside explicitly. Corrupt completed partials are removed. Lock files
  prevent concurrent downloads of the same target. Failed downloads can be
  retried with the same apply command. Redirects are restricted to HTTPS HF
  domains; proxy environment is not inherited by the downloader.
* Memory admission reads host RAM plus **all visible ancestor cgroup v1/v2 hard
  limits and current usage**. It uses the tightest effective limit/headroom,
  not host RAM alone. The default 32 GiB minimum is a conservative configurable
  admission policy, not a measured peak requirement or a guarantee. Unknown or
  insufficient memory blocks apply before side effects and config generation
  before launch. Run in a separately approved sufficiently sized **bounded**
  scope/container, then check again. No scope creation, limit adjustment, process
  migration, or escaping the caller's limit is attempted. For a deliberately
  risky experiment, `native-setup ... --allow-low-memory` and generation's
  `--native-allow-low-memory` acknowledge OOM risk for that invocation only;
  neither raises a resource limit. Do not use this to misrepresent a 4 GiB schema
  server as a suitable inference process. Memory may change after admission.
* Installer logs/venv state and partial model files survive failure for diagnosis
  and retry. An interrupted initial venv creation without its managed marker is
  not adopted automatically; select a new path or explicitly remove only that
  incomplete environment. Never delete unrelated services/caches to make room.

## Apple Silicon macOS provisioning

`--root` defaults to MPS on native arm64 macOS, CUDA elsewhere. Existing JSON
configs retain their saved device (missing `device` still means CUDA for schema
compatibility). `--device` and `--models` are explicit overrides for `--root`
only; they cannot override a saved config. Intel macOS and macOS CUDA installation
fail before writes. MPS on Linux also fails; no silent CPU substitution occurs.

Use an **internal-drive** root for the interpreter, checkout, runs and output.
Large weights may stay on an external volume through `--models`. No runtime is
copied from an earlier working environment and no weights are copied into the
checkout. Existing model files must still pass the packaged sizes and SHA256s.

The macOS installer runs under **Python 3.12.12**, creates a dedicated symlinked
venv (required for uv-managed macOS Python's dylib layout), installs **torch
2.14.1 / torchvision 0.29.1 from PyPI**, then the unchanged pinned ComfyUI
requirements under matching constraints. It does not install torchaudio, which
this pinned requirements file does not request, and does not use CPU/CUDA wheel
indexes. The CPython 3.12 macOS 14+ arm64 wheel metadata was checked directly
against PyPI; filenames, source URLs, sizes and digests are retained in
`macos-provisioning-wheels.json`. This metadata evidence is **not** a fresh
installation or inference receipt. Transitive dependencies remain resolver-based,
not fully hash-locked. Other Python versions fail with a copyable rerun instruction;
the installer never downloads or replaces a global Python interpreter.

Run from the Remesher checkout, substituting fresh internal and existing external
paths below. `uv run --python` may need separate approval to obtain that Python
and the CLI dependencies; it does not reuse the successful inference venv.

```sh
ROOT="$HOME/.hermes/cache/scratch/remesher-macos-public-provisioning"
MODELS="/Volumes/T9/remesher-macos-inference/ComfyUI/models"

# Read-only plan: model bytes are the inventory total, not a download promise.
uv run --python 3.12.12 comfy-prompt-cli native-setup plan \
  --root "$ROOT" --models "$MODELS" --device mps

# After explicit package-install and low-memory experiment approval:
# Intentionally NO --allow-download: reuse and hash-check the four external weights.
uv run --python 3.12.12 comfy-prompt-cli native-setup apply \
  --root "$ROOT" --models "$MODELS" --device mps \
  --allow-install --allow-low-memory

# Only after apply exits 0 and writes this config:
uv run --python 3.12.12 comfy-prompt-cli native-setup check \
  --config "$ROOT/native-setup.json" --allow-low-memory

# Idempotence: no package/model installation approval on the second apply.
uv run --python 3.12.12 comfy-prompt-cli native-setup apply \
  --config "$ROOT/native-setup.json" --allow-low-memory
```

For new model storage, approve the displayed bytes and add `--allow-download`
separately. Read `venv/native-setup.log` on package failure. Preserve failed roots
for diagnosis; do not overwrite an unmanaged venv or reset an existing checkout.
Both venv and checkout have nonblocking setup locks, including when two separate
venvs request the same checkout.

macOS memory admission reads physical unified memory through `sysctl hw.memsize`
and a conservative free + inactive + speculative page estimate through `vm_stat`.
Missing/malformed counters fail closed. Swap is **not** counted as RAM. MPS has a
32 GiB admission floor even if `minimum_memory_gib` is lowered. The previously
successful 8 GiB experiment required heavy swap: it is not silently admitted or
advertised as a normal hardware recommendation. `--allow-low-memory` is required
on every setup check/apply and `--native-allow-low-memory` on config-based
generation; the override is never saved. External weights do not move system swap.

macOS installation requires 8 GiB package/checkout headroom plus a 5 GiB reserve
on the destination volumes before writing. During package/git commands the owner
samples runtime-volume free space each second and stops its child group below
5 GiB. This is a guard, not a filesystem quota; other writers and in-flight writes
can race it. Keep the runtime internal so it protects the system/swap volume.
Generation still needs its own bounded time and disk supervision.

The config accepts `mps_fallback` (default true) and `omp_num_threads` (1..256 or
null). MPS resolves null threads to 1 and passes `PYTORCH_ENABLE_MPS_FALLBACK=1`
and `OMP_NUM_THREADS=1` explicitly to both the probe and the owned child. Set
`mps_fallback=false` for strict unsupported-op failure. This permits individual
unsupported MPS operations to fall back, not silently selecting a CPU device;
the tensor probe and owned server's MPS identity must still pass. Linux retains
its previous environment unless threads are explicitly configured. No arbitrary
environment dictionary, shell command, or install URL is accepted.

Provisioning `ready=true` does not certify a fresh image-to-GLB generation. Record
the fresh root, reused external-weight paths, check JSON, install log, interpreter
versions, disk reserve and second-apply result separately from inference evidence.

## Historical code/test evidence

Current integrated verification and delivery gates are in the
[release task index](release-readiness.md); the counts below describe earlier
source revisions, not the current full suite.

On the historical setup revision derived from `829f821931ab2bee1df4655a241cd2fa77621bb3`:
`uv run --with pytest pytest -q` passed **164 tests** (no skips), and
`sh scripts/verify-native-wheel.sh` passed **71 packaged native tests** (no skips)
from a separate site-packages installation. These include real disposable HTTP
children and real temporary venv creation; model transport and package network
installation are deliberately fixtures. No shared acceptance runtime was changed.
New native modules/tests pass Ruff. The existing CLI module retains the same
72 baseline diagnostics, with no new diagnostic identities after line mapping.
The wheel run also exercised unlocked dependency resolution (Typer 0.27.3);
its legacy `typer[all]` extra warning is non-fatal. No live GPU result is claimed.

## Delivery and acceptance task index

| Boundary | State / evidence |
|---|---|
| TRELLIS setup plan/check/apply, config routing, resumable hash-checked downloads | Implemented; `tests/test_native_setup*.py` |
| Per-run configured model visibility and owned-child lifecycle | Protocol fixtures in `tests/test_native_runtime.py`, `tests/test_native_cli.py` |
| Installed wheel packaging/CLI | `sh scripts/verify-native-wheel.sh`; isolated wheel env, no repository import fallback |
| Real package/network model installation | Separate runtime acceptance; fixture installer tests do not certify fresh network installs |
| Real TRELLIS structure → shape → texture → UV/PBR → GLB on Spark | Passed via actual combined Hermes plugin → wheel CLI → owned child; [wrestler acceptance and limitations](trellis-plugin-acceptance.md) |
| Pixal3D setup preset and real inference | Implemented and tested through installed wheel/plugin on Spark; [separate pipeline and quality results](pixal3d-acceptance.md) |
| CPU/MPS/ROCm generation | Not certified; no fallback claims |

Schema-v1 configs now accept `"model": "pixal3d"`; missing `model` retains
TRELLIS compatibility. To reuse a prepared runtime, create a **separate** config
with the same venv/checkout/models paths and distinct runs/output paths, then
run plan/check/apply with that config. Downloads still require `--allow-download`;
do not pass `--allow-install` when reusing an approved working environment.
The plugin derives the model from this config and snapshots it per job. Explicit
CLI/plugin model settings that disagree with the config are rejected.

Pixal3D defaults to `MoGeInference` → horizontal/degrees `MoGeGeometryToFOV` →
`Pixal3DConditioning.camera_angle_x`. CLI `--native-camera-angle 49.13` opts out
of estimation for a diagnostic; the preset still verifies all five assets.
This does not claim upstream crop/cascade/multiview parity. The unchanged
TRELLIS graph does not run MoGe.
