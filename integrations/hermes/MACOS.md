# macOS / MPS: prepared-runtime route

Plugin 0.3.0 supports the Linux and macOS POSIX adapter lifecycle. Windows is
not supported. macOS support here is **image-to-GLB with a separately prepared
runtime**, not automatic installation, rigging, or universal model certification.

## Configure explicitly

Prepare and verify a dedicated ComfyUI Python environment and checkout first.
Do not use the Linux CUDA installer on macOS. `native_config` readiness still
uses the Linux memory policy and CPU/CUDA schema; use the explicit runtime fields
below on macOS, not a forged `ready` receipt or a low-memory-policy bypass.
No dependencies or model weights are installed by plugin registration or health.

```json
{
  "cli": "/absolute/remesher/.venv/bin/comfy-prompt-cli",
  "backend": "native-local",
  "native_python": "/absolute/internal-runtime/.venv/bin/python",
  "native_checkout": "/absolute/internal-ComfyUI",
  "native_models": "/Volumes/YourSSD/ComfyUI/models",
  "native_device": "mps",
  "native_model": "trellis2",
  "native_preset": "quality-1536-solid768",
  "max_timeout_seconds": 43200,
  "environment": {
    "PYTORCH_ENABLE_MPS_FALLBACK": "1",
    "OMP_NUM_THREADS": "4"
  }
}
```

Paths are placeholders. Preserve the venv interpreter path, including symlinks.
`native_models` is optional, must be an existing absolute directory, and is
mutually exclusive with `native_config`. It generates a per-job
`--extra-model-paths-config`; cache environment variables are not model roots.
Inspect/publish with `scripts/configure.py` as described in the README.

MPS selects ComfyUI's automatic device discovery: there is **no `--mps` flag**
in pinned ComfyUI `7a28332047b6af638dc6c7f72ef3481a718769fd`.
The launcher omits both `--cpu` and `--cuda-device`, then requires the identified
owned server's primary `/system_stats` device to be `mps`. Missing/CPU device
reports fail closed and trigger owned-child cleanup. CUDA remains the default
and retains `--cuda-device 0`; CPU retains `--cpu`.
`PYTORCH_ENABLE_MPS_FALLBACK` is an explicit `0`/`1` opt-in for unsupported
operations, not permission to silently accept a CPU-only server. Explicit
`OMP_NUM_THREADS` accepts integer strings 1–64. Neither variable is inherited
from the ambient Hermes environment.

## Long jobs are opt-in twice

The default request remains 900 seconds; the default operator ceiling remains
1800 seconds on every platform. `max_timeout_seconds` (or
`REMESHER_MAX_TIMEOUT_SECONDS`) accepts integers 900–43200. Raising the ceiling
**does not raise the default request**. For an authorized long quality run:

```json
{"image": "/absolute/prepared.png", "timeout_seconds": 43200}
```

The detached plugin supervisor bounds the entire launch/inference/transfer/asset
inspection lifecycle. The same requested value reaches the real CLI's native
inference/transfer deadline, with a hard 43200-second native cap. CLI standalone
startup remains a separate 120-second default; plugin startup consumes its outer
budget. There is no unbounded wait or automatic extension/retry. Cleanup can add
12 seconds for native CLI SIGTERM plus 5 seconds for final SIGKILL reaping.
If the CLI still cannot be reaped, its receipt is `failed` with
`cleanup_pending: true`; new jobs are blocked until an operator investigates and
reconciles that receipt. Never clear this flag just to retry a possibly live job.
Host/kernel stalls can still exceed wall-clock targets; these are not realtime
guarantees. Normal SIGKILL/host failure can leave a separately owned server.

Before a low-memory run, explicitly approve the memory/swap risk, measure system
and model-volume free space, and monitor memory, swap, disk reserve, progress and
logs. The plugin does not impose a memory or disk-reserve guard. External models
do not relocate system swap. Keep the Mac awake for long jobs. A two-step sampler
smoke is not a quality preset and is not substituted for quality defaults.

## Evidence and limits

A preserved direct ComfyUI graph replay on Apple M2, 8 GiB, macOS 27 completed
in 09:28:03 with MPS, Python 3.12.12, torch 2.14.1 and torchvision 0.29.1.
The graph used 12/20/12/12 sampler steps, shape1536, solid768 and texture4096.
Its final GLB SHA-256 is
`d562871c56704e6bf90aaf121f6ee06ea7e8da575f4990c1d0fdd64977a2a949`
(509376 vertices, 912552 faces). Independent Blender import/render succeeded;
reported visual quality was coherent with hand/face limitations.

This historical replay was **not submitted by the Hermes plugin** and omitted
the newer final smooth-normal node. It is graph/runtime/device evidence, not a
full plugin-owned GPU acceptance run. Real CLI HTTP-fixture lifecycle tests
separately cover registration, settings, MPS argv/device checks, long-budget
forwarding, receipts, download and cleanup; they do not run models. A final
plugin-owned real inference run with the current graph remains an acceptance gate.

The successful experiment used an internal-drive runtime and external weights.
An earlier SSD-executed Python blocked in kernel I/O; its cause is unproven.
Do not generalize this to SSD incompatibility. Keep runtime and models separate
as a tested operating arrangement, not as a hardware requirement.

The macOS platform declaration does not extend to CLI rigging/auto-skin atomic
publication: existing Darwin no-replace rename support remains a separate gate.
No remote cancellation, gallery, rendering tool, Windows support or catalog
admission is added by this release.
