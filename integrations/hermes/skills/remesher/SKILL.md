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
   are unnecessary. Prefer native-local with `native_config` pointing to an
   approved schema-v1 setup config. Alternatively use absolute `native_python`
   (preserve venv symlinks) and `native_checkout` containing `main.py`.
3. With user authorization, write a **candidate JSON file**, using the README
   schema: `cli`, `backend`, backend-specific settings and optional allowlisted
   `environment`. Config mode reads `model` (`trellis2` default or `pixal3d`).
   Set `native_preset: quality-1536-solid768` in an approved native settings file
   for everyday quality generation: shape1536, solid768 repair, atlas4096,
   no decimation/no precluster cap, bounded filling and explicit smooth normals.
   Explain the extra memory/time before opting in. Use `native_preset: fast`
   for explicit 512/no-repair/1024/80000 smoke jobs. Omission preserves old CLI
   behavior, not the tested quality recipe. Request preset overrides settings
   preset; explicit scalar controls must agree or the request is rejected.
   Do not mix `native_config` with explicit runtime paths/device/server. For manual native-local, set
   `native_device` to `cuda`, `cpu` or `mps`. On macOS use the prepared-runtime
   route in `MACOS.md`, optional explicit `native_models`, not Linux native-config
   readiness or the CUDA installer. MPS must be reported by the owned server.
   Never insert shell strings or extra
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
6. Read the actual CLI `docs/native-setup.md` contract. Run JSON `native-setup
   plan --config <path>`, then `check`; explicitly authorized `apply` without
   install/download opt-ins reuses existing resources. Require exit 0 and
   `ready=true` from check/apply. Never use legacy Comfy3D downloaders for native
   weights or silently acknowledge low-memory risk. Apply approved bounded
   resource changes separately, never to unrelated services. Configuration
   inspection is not GPU acceptance. The plugin snapshots setup JSON per job,
   replacing only runs/output with private job paths. CLI readiness is rechecked
   before launch and configured model paths reach the owned child automatically.

## Generation and delivery

1. Call `remesher_health`. Server-mode `healthy` means `/system_stats` connectivity
   only. Native-local returns `configured` without starting a server, and explicitly
   leaves model/GPU readiness unverified. Never describe either as GPU certification.
2. Ensure the user authorized the image upload/local server startup and GPU usage.
   Native input must already be foreground-masked and square-composited on black;
   the plugin/CLI do not remove backgrounds. Preserve source/mask/prepared images
   and pad enough to retain hands/feet. Do not mistake gray clothing for background.
   Call `remesher_generate` once with absolute PNG/JPEG/WebP `image` (max 20 MiB).
   With configured quality, do not pass a face target or old scalar defaults.
   Optional `timeout_seconds`: 1–1800, default 900. For authorized long jobs,
   the operator may set `max_timeout_seconds` up to 43200, then explicitly request
   that budget; changing the ceiling does not change the 900-second default.
   Plan for startup, inference, transfer and asset inspection together.
   Save the returned job_id.
   Backend and paths are setup settings,
   not per-call model-controlled tool arguments.
3. Poll `remesher_job` every few seconds. States are `queued`, `running`,
   `succeeded`, `failed`, `timed_out` or `interrupted`. One active local job per
   profile; another submission returns `busy`. Never replay an ambiguous job.
4. On success call `remesher_assets`; report the actual path and hash. Validation
   is GLB header/length only, not geometry, rendering or inference provenance.
   Reads rehash outputs; `integrity_error` means no safe artifact delivery. Keep
   the original receipt and investigate rather than automatically regenerate.
   Verify the hash again when consuming an artifact.

Native-local deadlines allow up to 12 seconds plus 5 seconds final reaping for
the CLI to reap its owned server. SIGKILL/host crash can still leave a server
behind. `cleanup_pending: true` blocks new jobs until operator reconciliation;
never clear it without checking the prior owned processes. Existing native/comfy3d server jobs are **not remotely cancelled** by
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
