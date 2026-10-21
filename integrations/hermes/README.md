# Remesher for Hermes — first integration slice

Native Python plugin (`plugin.yaml` + `register(ctx)`) with a bundled namespaced
skill, wrapping the existing **ComfyUI-backed** `comfy-prompt-cli`. This is not a
new inference backend. No changes to the CLI, existing workflows, or ComfyUI are
required. No GPU provisioning, model downloads, Hermes dependency installation,
or active-profile changes happen at import, registration, doctor, or validation.

## Operator setup

Requires a POSIX host (tested on Linux), Python 3.11+, a separate installed
Remesher CLI environment, and an already running trusted ComfyUI/Comfy3D server
with the nodes/models needed by `examples/img_to_trellis2.json`.

From a Remesher checkout, `uv sync` prepares its own `.venv`; **do not install
Remesher into Hermes's Python environment**. Supply absolute paths in the
Hermes process environment (examples below are placeholders, not existing paths):

```sh
export REMESHER_CLI=/absolute/remesher/.venv/bin/comfy-prompt-cli
export REMESHER_CONFIG=/absolute/private/config.json
export REMESHER_WORKFLOW=/absolute/remesher/examples/img_to_trellis2.json
```

The CLI config uses the existing format, e.g. `{"server_url":"http://127.0.0.1:8188/"}`.
These values are operator configuration, never tool arguments. The executable
must be a file, not a shell command or `uv run` string. Workflow/config files must
remain available until the job starts. The server and executable are trusted;
process/environment isolation is **not an OS security sandbox**. HOME and PATH
are preserved; the CLI can access local files with the operator's permissions.
Images are uploaded to the configured server; obtain authorization before use.

Validate without installing or enabling anything:

```sh
hermes plugins doctor /absolute/remesher/integrations/hermes --ci
hermes plugins validate /absolute/remesher/integrations/hermes --json
```

For an explicitly authorized manual local install, copy this directory to
`$HERMES_HOME/plugins/remesher` (default `$HOME/.hermes/plugins/remesher`), preserving
`__init__.py`, `plugin.yaml`, and `skills/`. Do not overwrite an existing plugin
blindly. Enable it with `hermes plugins enable remesher`, then start a fresh
Hermes session. Use `skills_list` to discover `remesher:remesher`.
This implementation task does **not** perform that installation.

A future Hermes catalog entry should point to repository `remesher/remesher`,
`subdir: integrations/hermes`, and a full immutable commit SHA containing this
integration. Catalog submission and maintainer approval are separate from this
Remesher PR; a successful validator is not a catalog listing.

## Tools

| Tool | Inputs | Result |
|---|---|---|
| `remesher_health` | none | `healthy`, `unhealthy`, `timed_out`, `unavailable`; connectivity only |
| `remesher_generate` | absolute `image`; optional `timeout_seconds` (1–1800, default 900), `target_face_num` (1000–200000, default 80000) | `queued` plus `job_id`, or `busy` / structured rejection |
| `remesher_job` | `job_id` | persistent job state |
| `remesher_assets` | `job_id` | successful artifact paths, byte sizes, SHA-256 hashes, MIME types |

Example model arguments:

```json
{"image":"/absolute/character.png","timeout_seconds":900,"target_face_num":80000}
```

Use the returned ID for both read tools. Job IDs are 32 lowercase hex characters;
paths cannot be passed in place of IDs. Tools stay registered while unconfigured
so health can explain setup and existing artifacts remain discoverable by ID.

### Lifecycle and storage

- `queued → running → succeeded | failed | timed_out`. A worker that fails to
  finalize is reported `interrupted` after its deadline plus 30 seconds. This is
  an observation, not proof the backend stopped. Failed worker launch persists
  `failed`; a delayed worker will not submit after its deadline.
- One active local job per profile, guarded by an interprocess admission lock.
  There is no automatic retry or cross-profile/server-wide scheduler.
- A separate stdlib supervisor survives normal Hermes exit and enforces the CLI
  deadline. It launches the explicit executable with an argv list, no shell, a
  dedicated working directory, and a small environment allowlist. `PYTHONPATH`,
  Python activation, uv settings, and ambient API keys are not forwarded.
- The input is copied into a private job directory (extension PNG/JPEG/WebP,
  maximum 20 MiB); decoding remains the backend's responsibility. All local CLI
  process-group members are killed at deadline. Health has a 25-second bound.
- **Local timeout is not remote cancellation.** ComfyUI may still be running a
  submitted prompt. Inspect its queue/history before retrying. This first slice
  does not parse the human CLI log into a reliable remote prompt ID, provide a
  cancel endpoint, or interrupt other users' ComfyUI jobs.
- State, request metadata, input, output, and a capped 1 MiB diagnostic log live
  under `plugin_data_dir("remesher")/jobs/<job_id>/`. This follows `HERMES_HOME`,
  survives plugin updates, and never uses the plugin source directory for data.
  State replacement is atomic. Keep your job IDs; there is no job-list tool yet.
- Success requires CLI exit zero and at least one `.glb` with matching magic,
  version 2, and declared length. Inspection accepts at most 16 files / 512 MiB
  combined. This is **header validation**, not full glTF validation, nonempty
  geometry, rendering, rigging quality, or proof that a GPU generated the bytes.
  The asset response is a saved manifest; external deletion/modification is not
  revalidated on every read.
- The CLI's downloads are not filesystem-quota sandboxed. Use a trusted server
  and storage quota if needed; the inspection cap is not a download-size cap.
  Logs may contain private server details; they are not returned automatically.
  Retention is operator-managed; no automatic deletion. Remove only completed
  owned job directories after saving needed assets. Do not remove running jobs
  or update/uninstall the plugin while a supervisor is active. A host crash or
  killed supervisor is not a resumable/replayable remote job transaction.

## Reproducible validation

From the repository root:

```sh
uv sync
REMESHER_TEST_CLI="$PWD/.venv/bin/comfy-prompt-cli" \
  python -m unittest discover -s integrations/hermes/tests -v
uv run --with pytest pytest tests -q
uvx ruff check integrations/hermes
uvx ruff format --check integrations/hermes
hermes plugins doctor integrations/hermes --ci
hermes plugins validate integrations/hermes --json
```

The contract suite uses actual subprocesses. Its real-CLI test uses the current
CLI and repository Trellis2 workflow against a **local HTTP fixture**, covering
health, image upload, prompt submission, history polling, and downloading fixture
GLB bytes. Other cases use fake executable fixtures for timeout/failure injection.
Without `REMESHER_TEST_CLI`, the real-CLI case explicitly skips. None is a GPU test.

Initial verification used Hermes `v0.22.2+1690.g9e01b44`, public `ctx.register_tool`,
`ctx.register_skill`, and `plugins.plugin_storage.plugin_data_dir`. Doctor checks
real discovery/import/registration in an isolated temporary Hermes home; validate
checks manifest/tool correspondence, capability probing, and security scans.
The official plugin guide and installed SDK were inspected rather than inventing
an SDK interface. No minimum Hermes version is claimed beyond those verified
APIs; re-run doctor/validation on the intended deployment version.

## Explicit follow-up work

Real GPU acceptance on an authorized existing endpoint; remote job IDs and safe
cancellation/reconciliation; disk quotas/retention and stronger glTF validation;
job browsing; desktop viewer/polish; catalog submission; MCP; text-to-3D/rigging;
and native local Trellis2/Pixal3D backend work. These are **not** delivered here.
