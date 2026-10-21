---
name: remesher
description: Configure and inspect Remesher setup, generate GLBs from local images with comfy3d or native backends, and retrieve persistent job artifacts.
---

# Remesher setup and image-to-GLB

## Agent-configurable setup

1. Discover the installed plugin directory and read its `README.md`. Inspect the
   actual Remesher CLI's `image-to-glb --help` before selecting a native backend.
   Keep Remesher dependencies out of Hermes's Python. Preserve existing settings;
   do not mutate an active profile, install packages or download weights implicitly.
2. Choose `comfy3d` (default existing Comfy3D server), `native` (existing numeric
   loopback native ComfyUI server), or `native-local` (CLI-owned local child).
   Native modes require the native CLI implementation; legacy config/workflow
   are unnecessary. Native-local requires absolute `native_python` (preserve
   venv symlinks) and `native_checkout` containing `main.py`.
3. With user authorization, write a **candidate JSON file**, using the README
   schema: `cli`, `backend`, backend-specific settings and optional allowlisted
   `environment`. For native-local, set `native_device` to `cuda` or `cpu` and
   `native_model` to `trellis2` or `pixal3d`. Never insert shell strings or extra
   arguments. Device/cache variables must be explicit in `environment`; ambient
   CUDA/HF/Torch variables are scrubbed along with Python/uv activation and tokens.
4. Run `python <plugin>/scripts/configure.py --input <candidate.json>` for
   read-only validation and model-file inspection. `configured` means paths and
   settings only, not importability, model visibility or GPU readiness. Missing
   default model files may be supplied through ComfyUI's own `extra_model_paths.yaml`;
   this script does not parse or modify it. Cache locations are **not** model roots.
5. With authorization, publish to a **new explicit absolute file**:
   `python <plugin>/scripts/configure.py --input <candidate.json> --output <settings.json>`.
   Existing files/symlinks are refused. Set `REMESHER_SETTINGS` in the intended
   Hermes process environment and start a fresh session after authorized changes.
   The script never edits profile config, `.env`, dependencies or installation.
6. Provisioning is a separate boundary: the checked native CLI revision
   `829f821931ab2bee1df4655a241cd2fa77621bb3` has no native setup/download script.
   Do not invent one or use the legacy Comfy3D downloader for native weights.
   If a newer checkout ships a setup script, discover and read its source/help
   and get permission for its actual side effects before use. The bundled
   `scripts/configure.py` configures **this plugin only**. Verify native graph/model
   enumerations on the selected server; file existence alone is insufficient.

## Generation and delivery

1. Call `remesher_health`. Server-mode `healthy` means `/system_stats` connectivity
   only. Native-local returns `configured` without starting a server, and explicitly
   leaves model/GPU readiness unverified. Never describe either as GPU certification.
2. Ensure the user authorized the image upload/local server startup and GPU usage.
   Call `remesher_generate` once with absolute PNG/JPEG/WebP `image` (max 20 MiB).
   Optional `timeout_seconds`: 1–1800, default 900; `target_face_num`: 1000–200000,
   default 80000. Save the returned job_id. Backend and paths are setup settings,
   not per-call model-controlled tool arguments.
3. Poll `remesher_job` every few seconds. States are `queued`, `running`,
   `succeeded`, `failed`, `timed_out` or `interrupted`. One active local job per
   profile; another submission returns `busy`. Never replay an ambiguous job.
4. On success call `remesher_assets`; report the actual path and hash. Validation
   is GLB header/length only, not geometry, rendering or inference provenance.
   Reads rehash outputs; `integrity_error` means no safe artifact delivery. Keep
   the original receipt and investigate rather than automatically regenerate.
   Verify the hash again when consuming an artifact.

Native-local deadlines allow up to 12 seconds of additional cleanup grace for
the CLI to reap its owned server. SIGKILL/host crash can still leave a server
behind. Existing native/comfy3d server jobs are **not remotely cancelled** by
local timeout. Inspect queue/history before retrying, and never globally interrupt
another user's jobs. Supervisors may continue after Hermes exits; only queued
receipts are consumed, never running/terminal receipts. Artifact inspection shares
the deadline; overdue bytes are not success.

Artifacts/logs live in profile plugin-data storage, not the checkout. Native-local
run/server logs live under the job's `native-runs`; server log size is not capped.
Don't update code or delete job storage while a worker is active. Inspect logs
locally and redact private details before sharing. No cancel, rigging, text
input, viewer or MCP surface is provided. Never claim fixture tests are real GPU
inference evidence.
