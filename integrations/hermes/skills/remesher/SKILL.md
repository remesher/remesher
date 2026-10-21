---
name: remesher
description: Generate a GLB from a local image with the Remesher tools, inspect persistent job status, and retrieve artifacts from a configured ComfyUI backend.
---

# Remesher image-to-GLB

1. Call `remesher_health`. Healthy means `/system_stats` connectivity only, not
   installed Trellis2 nodes/models or a successful GPU generation.
2. Ensure the user authorized uploading this image to the configured server and
   using its GPU resources. Never provision services or download models implicitly.
3. Call `remesher_generate` once with an absolute local PNG/JPEG/WebP `image` path.
   Optional `timeout_seconds` is 1–1800 (default 900); `target_face_num` is
   1000–200000 (default 80000). Inputs are limited to 20 MiB. Save the returned job_id.
4. Poll `remesher_job` with that ID, no faster than every few seconds. Local states
   are `queued`, `running`, `succeeded`, `failed`, `timed_out`, or `interrupted`.
   A second concurrent local submission returns `busy` rather than queueing.
5. On success, call `remesher_assets` and report the actual artifact path and hash.
   Validation checks the GLB header only; it does not prove mesh quality or rendering.
   Both read tools rehash artifacts. `integrity_error` means the saved output is
   missing, changed, symlinked, or unreadable: do not deliver stale paths or claim
   success. Preserve the original receipt for investigation; do not regenerate
   automatically. Verify the hash again when consuming the artifact.

A local timeout or interrupted worker does **not** cancel the server-side ComfyUI
prompt. Do not blindly retry: inspect the configured server queue/history first.
The supervisor may continue after Hermes exits, up to the submitted deadline.
Never restart a running/terminal worker to retry it: only a queued receipt may
be consumed. Inspection shares the CLI deadline; overdue bytes are not success.
The first slice intentionally has no cancel, rigging, text generation, desktop
viewer, native local inference backend, or MCP surface.

If unavailable, ask the operator to configure absolute paths `REMESHER_CLI`,
`REMESHER_CONFIG`, and `REMESHER_WORKFLOW` as described in the plugin README.
Do not change the active Hermes configuration or install dependencies without
permission. Artifacts and private logs remain in the profile's plugin-data
storage, not the plugin checkout. Logs may contain server details; inspect locally
and redact before sharing. Never claim fixture tests are real GPU evidence.
