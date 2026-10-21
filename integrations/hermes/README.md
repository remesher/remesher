# Remesher for Hermes

Python plugin (`plugin.yaml` + `register(ctx)`) with a bundled setup/generation
skill. It wraps an **isolated Remesher CLI**, never imports its dependencies into
Hermes, and preserves `comfy3d` as the default. Native modes require a CLI that
implements the native contract below (PR18); this plugin does not install it.
Nothing provisions services, downloads models, or changes an active profile at
import, registration, doctor, validation, health, or configuration inspection.

Combined native-config real GPU evidence and remaining review/quality gates:
[TRELLIS wrestler acceptance](../../docs/trellis-plugin-acceptance.md).

## Backend and configuration contract

Requires POSIX, Python 3.11+, a separately installed CLI, and trusted executable,
checkout and settings paths. These are operator/agent setup settings, **not tool
arguments**. Obtain authorization before configuration writes or generation.

| Backend | Required settings | Execution |
|---|---|---|
| `comfy3d` (default) | `cli`, `config`, `workflow` | Existing ComfyUI/Comfy3D server; legacy CLI options unchanged |
| `native` | `cli`; optional `native_server`, `native_model` | Existing numeric-loopback HTTP native ComfyUI server |
| `native-local` | `cli`, `native_python`, `native_checkout`; optional `native_device`, `native_model` | CLI starts and owns a local ComfyUI child |
| `native-local` with setup config | `cli`, `native_config` | Verified TRELLIS setup config, private job snapshot, owned local child |

All file paths must be existing absolute paths. `cli` and `native_python` must
be executable; `native_checkout` must contain `main.py`. Interpreter symlinks
are **not resolved**, preserving venv identity. Defaults: native server
`http://127.0.0.1:8188`, device `cuda` (`cpu` also accepted), model `trellis2`
(`pixal3d` also accepted). Native modes need neither legacy config nor workflow.
The generated native graph is owned by the CLI, not a plugin-supplied workflow.

Use an absolute `REMESHER_SETTINGS` path to a structured JSON file. When set it
is authoritative: environment settings are **not merged** into it. Unknown keys,
invalid types/enums, non-loopback native origins, and unsupported environment
keys are rejected before launch. No arbitrary argv, shell command, setup command,
Python import path, or token field is accepted.

Example native-local settings (paths are placeholders):

```json
{
  "cli": "/absolute/remesher/.venv/bin/comfy-prompt-cli",
  "backend": "native-local",
  "native_python": "/absolute/native-venv/bin/python",
  "native_checkout": "/absolute/ComfyUI",
  "native_device": "cuda",
  "native_model": "trellis2",
  "environment": {
    "CUDA_VISIBLE_DEVICES": "0",
    "HF_HOME": "/absolute/cache/huggingface",
    "TORCH_HOME": "/absolute/cache/torch"
  }
}
```

Without `REMESHER_SETTINGS`, scalar keys come from their uppercase `REMESHER_`
counterparts, e.g. `REMESHER_BACKEND`, `REMESHER_NATIVE_PYTHON` and
`REMESHER_NATIVE_CHECKOUT`. Existing default setup remains valid:

```sh
export REMESHER_CLI=/absolute/remesher/.venv/bin/comfy-prompt-cli
export REMESHER_CONFIG=/absolute/private/config.json
export REMESHER_WORKFLOW=/absolute/remesher/examples/img_to_trellis2.json
```

Legacy CLI config example: `{"server_url":"http://127.0.0.1:8188/"}`.
The only explicit `environment` keys are `CUDA_VISIBLE_DEVICES`, `HF_HOME`,
`HF_HUB_CACHE`, `TORCH_HOME`, `XDG_CACHE_HOME`, `LD_LIBRARY_PATH` and
`PYTORCH_CUDA_ALLOC_CONF`. Cache/library paths must be absolute; library lists
are colon-separated with no empty entries. These overrides are snapshotted in
the private request and forwarded to the CLI/native child. Ambient versions of
these variables are **not** forwarded. HOME, PATH, locale, TMPDIR and TLS
certificate paths are retained; Python/uv activation and API tokens are not.
This is process/dependency isolation, **not an OS security sandbox**.

### Agent-configurable inspection and publication script

Write a candidate JSON using the schema above, then run the bundled script:

```sh
# Read-only local path/settings/model-file inspection; no server startup.
python /absolute/plugin/scripts/configure.py --input /absolute/candidate.json
# Explicitly authorized publication to a NEW 0600 file; never overwrites.
python /absolute/plugin/scripts/configure.py --input /absolute/candidate.json \
  --output /absolute/private/remesher-settings.json
```

The report includes normalized settings, default model-file existence and the
presence of `extra_model_paths.yaml` for native-local. This does not parse extra
paths, hash weights, load models, or establish GPU readiness. Point the intended
Hermes process at `REMESHER_SETTINGS=/absolute/private/remesher-settings.json`;
restart that session after authorized environment changes. Neither script nor
plugin edits `.env`, `config.yaml`, an installed plugin, or another profile.
For updates, inspect and publish a new file rather than overwriting a live one.

### Verified native setup configuration (recommended)

The combined PR18/PR19 CLI implements [native-setup](../../docs/native-setup.md).
Use its actual JSON contract; do not use legacy Comfy3D downloaders:

```sh
comfy-prompt-cli native-setup plan --config /absolute/native-setup.json
comfy-prompt-cli native-setup check --config /absolute/native-setup.json
# Explicitly authorized reuse only: no installs or downloads without opt-ins.
comfy-prompt-cli native-setup apply --config /absolute/native-setup.json
```

Check/apply must exit 0 with `ready=true` before generation. Configure the plugin:

```json
{
  "cli": "/absolute/isolated-cli/bin/comfy-prompt-cli",
  "backend": "native-local",
  "native_config": "/absolute/native-setup.json"
}
```

`REMESHER_NATIVE_CONFIG` is the equivalent scalar environment setting. Config
mode supports TRELLIS only and rejects explicit interpreter, checkout, device
or server settings. Health/configure inspect schema-v1 JSON and path structure,
not dependency availability, hashes or memory; `configured` is not `ready`.
The CLI rechecks full setup readiness before each launch, without downloads.
Each job saves a 0600 `native-setup.json` snapshot with **only `runs` and `output`
replaced by private job paths**. The original setup config remains unchanged.
The CLI receives `--native-config`, not conflicting `--out-dir`/runtime flags.
Its configured model root is passed to the owned child automatically. The
plugin never changes cgroup limits or acknowledges low-memory risk for you.

The input must already be background-removed and square-composited onto black.
Neither the plugin nor the generation CLI automatically removes backgrounds.
Keep original, mask and prepared image separately; protect hands/feet with
padding. A valid GLB header is not a topology, anatomy or production-quality pass.

**Model visibility:** cache environment variables are not ComfyUI model search
paths. Put the native weights in the selected checkout's `models` directories,
or configure that checkout's supported `extra_model_paths.yaml` separately with
authorization. Config mode passes its model root automatically; the standalone
CLI also supports `--native-models` with explicit launcher paths. Required names:

- `diffusion_models/trellis_2_int8_convrot.safetensors` or
  `diffusion_models/pixal3d_int8_convrot.safetensors`;
- `clip_vision/dino_v3_L_naf_fp32.safetensors`;
- `vae/trellis_2_shape_vae_bf16.safetensors`;
- `vae/trellis_2_texture_vae_bf16.safetensors`.

Native generation validates the CLI's graph and model enumerations against the
server's `/object_info` before upload/queueing. A file present locally is not
proof of model visibility or valid weight contents.

### Exact native CLI invocation

Common options: `image-to-glb --image <copied-input> --out-dir <job>/output
--filename-prefix hermes_<job-id> --target-face-num <faces> --timeout <seconds>`.
Native adds `--backend native --native-model <model> --native-server <origin>`.
Native-local instead adds `--backend native-local --native-model <model>
--native-python <python> --native-checkout <checkout> --native-device <device>
--native-runs <job>/native-runs`. Every argument is a separate argv entry.
The CLI owns its port/startup defaults; no unsupported future options are used.

## Tools and lifecycle

| Tool | Result |
|---|---|
| `remesher_health` | `healthy/unhealthy` connectivity for server modes; `configured` path validation only for native-local, which never starts a server; may return `timed_out/unavailable` |
| `remesher_generate` | Inputs: absolute local PNG/JPEG/WebP `image` (max 20 MiB), optional `timeout_seconds` 1–1800 (900 default), `target_face_num` 1000–200000 (80000 default). Returns `queued` + job_id or `busy`/rejection |
| `remesher_job` | Persistent status by 32-character lowercase hex job_id |
| `remesher_assets` | Successful GLB paths, byte sizes, SHA-256 and MIME types |

Health always reports `gpu_generation_verified: false`. For native-local it
also reports `model_visibility_verified: false`. `configured` is not `healthy`
and neither is inference evidence. Tools stay registered while unconfigured so
health can explain setup and old job IDs remain readable.

- States: `queued → running → succeeded | failed | timed_out`. A supervisor that
  misses its deadline plus 30 seconds is observed as `interrupted`, never replayed.
  One active job per profile; per-job and admission locks; no automatic retry.
- An independent stdlib supervisor survives normal Hermes exit. It uses argv
  lists, a private working directory, a capped 1 MiB CLI log and an absolute
  execution/inspection budget. Native-local gets up to **12 extra seconds of
  cleanup grace**: SIGTERM lets the CLI reap its separately-sessioned server,
  then the supervisor kills the CLI group. A dead/unresponsive CLI may leave its
  owned server behind: cleanup is not guaranteed after SIGKILL/host crash.
- Native-local server logs and run directories live under the private job's
  `native-runs`; their size is not capped by the plugin. Operator storage quotas
  are recommended. Do not update code or remove job data while a worker is active.
- **Local timeout is not remote cancellation.** Existing native/comfy3d servers
  are never globally interrupted. Inspect queue/history before retrying. Native
  local cleanup is session ownership, not a remote cancel API. No remote prompt
  ID/cancel tool is exposed; `remote_cancellation_supported` remains false.
- Storage: `plugin_data_dir("remesher")/jobs/<job_id>/`, following HERMES_HOME,
  separate from plugin source. Input and environment are snapshotted; executable,
  checkout, workflow and config paths must remain stable until completion.
- State uses atomic replacement with file/directory fsync; artifacts and their
  output directory are synced before success. Kernel/filesystem stalls can exceed
  time budgets; these are not hard realtime or distributed durability guarantees.
- Success requires exit zero plus GLB v2 header/length validation, at most 16 files
  and 512 MiB combined. This is not full glTF/geometry/render validation or GPU
  provenance. Reads rehash artifacts against receipts; missing, changed, symlinked
  or unreadable output returns `integrity_error` without stale assets. Recheck
  hashes when consuming artifacts. The filesystem/operator are trusted.
- Retention is manual. Keep job IDs; no job-list tool yet. Inspect logs locally
  and redact private paths/server information before sharing.

## Validation and installation

```sh
hermes plugins doctor /absolute/remesher/integrations/hermes --ci
hermes plugins validate /absolute/remesher/integrations/hermes --json
```

These inspect the plugin without installing/enabling it. For an authorized
manual install, copy the **entire** directory (including `scripts` and `skills`)
to `$HERMES_HOME/plugins/remesher`, avoiding blind overwrite; enable with
`hermes plugins enable remesher`, start a fresh session and discover
`remesher:remesher`. This implementation does not perform that installation.
Catalog listing/approval is separate; a validator pass is not a catalog listing.

From the repository root:

```sh
REMESHER_TEST_CLI="$PWD/.venv/bin/comfy-prompt-cli" \
REMESHER_TEST_NATIVE_CLI=/absolute/native-cli/.venv/bin/comfy-prompt-cli \
  python -m unittest discover -s integrations/hermes/tests -v
uv run --with pytest pytest tests -q
uvx ruff check integrations/hermes
uvx ruff format --check integrations/hermes
```

Native tests optionally use `REMESHER_TEST_NATIVE_PYTHON` (default sibling
`python` beside the native CLI). The legacy real CLI test exercises upload,
prompt, history and download against an HTTP fixture. Native tests exercise real
CLI argv, owned child startup, output transfer, timeout cleanup, and preservation
of an operator-managed server. The native fixture schema is deliberately
permissive; these are **transport/lifecycle tests, not node-schema, model or GPU
inference acceptance**. Missing CLI environment variables cause explicit skips.

Remaining work: real GPU acceptance, stronger glTF validation, remote IDs and
safe reconciliation/cancellation, quotas/retention, job browsing, desktop viewer,
catalog publication, MCP, text-to-3D and rigging.
