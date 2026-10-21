# Native ComfyUI backend: feasibility and bounded first slice

## Decision

Add an **optional backend**, not a fork or replacement for the existing Comfy3D
workflow. This change provides a read-only, executable native inventory preflight.
It does **not** add local process management or enable native generation in
`image-to-glb`. Legacy configuration, templates, rigging, and Docker paths are
unchanged. No models, packages, environments, or GPU resources are provisioned.

The official editor workflow and core node interfaces exist. However, this
investigation did not obtain and execute an equivalent **API-format** workflow
with Remesher's input overrides and GLB output handling. That is the gate for a
native generation backend, not grounds to silently substitute node names in
`examples/img_to_trellis2.json`. The downloaded official graph contains editor
widgets, switch/lazy branches, previews and save nodes; it is not `/prompt` JSON.

## Reproducible inventory check

Against an operator-managed local ComfyUI server:

```sh
uv run python -m comfy_prompt_cli.native_preflight --server http://127.0.0.1:8188
```

Only GET `/system_stats`, `/object_info`, and `/models/{folder}` are used. Numeric
loopback HTTP origins only; no credentials, DNS, proxy environment, redirects,
job submission, installation or process killing. Each HTTP operation has a
5-second inactivity timeout (not a total wall-clock deadline). Use only against
a trusted local server; response bodies are not size-limited.

Exit status:

* **0**: inventory matches the pinned **combined single-image editor template**.
* **1**: missing node/model or a checked schema sentinel differs.
* **2**: invalid origin, unavailable server, or malformed/failed endpoint.

`generation_validated`, `hardware_validated`, and `workflow_api_validated` are
always false, including on exit 0. Model checks are exact advertised filenames,
not contents, hashes, licenses, successful loading, or enough memory. Both model
branches are inventoried even if the operator intends to use only one. Optional
model substitutions and subdirectory aliases intentionally do not pass this
exact-template inventory. A 404 model folder is reported as missing models.
Only three conditioning/stage schemas are checked; `schema_scope` enumerates
them. Other nodes are presence checks, **not** a full workflow compatibility test.
`server_stats` is reported verbatim and must not be interpreted as a successful
GPU inference probe. Custom nodes can shadow core names; independently launching
with custom nodes disabled remains a later acceptance requirement.

## Sources and exact findings

Reviewed official sources (retrieved October 21, 2026):

* Announcement: https://blog.comfy.org/p/trellis2-and-pixal3d-are-now-native
* TRELLIS.2 tutorial: https://docs.comfy.org/tutorials/3d/trellis2
* Pixal3D tutorial: https://docs.comfy.org/tutorials/3d/pixal3d
* Core revision: `7a28332047b6af638dc6c7f72ef3481a718769fd`
* Template revision: `d0e41fe5423f93db5b5872cf273d7b1af8aa68bc`
* Editor template: https://github.com/Comfy-Org/workflow_templates/blob/d0e41fe5423f93db5b5872cf273d7b1af8aa68bc/templates/3d_pixal3d_trellis2_image_to_model.json
* Node schemas: https://github.com/Comfy-Org/ComfyUI/blob/7a28332047b6af638dc6c7f72ef3481a718769fd/comfy_extras/nodes_trellis2.py
* Sparse convolution: https://github.com/Comfy-Org/ComfyUI/blob/7a28332047b6af638dc6c7f72ef3481a718769fd/comfy/ldm/trellis2/flexgemm.py
* Mesh processing: https://github.com/Comfy-Org/ComfyUI/blob/7a28332047b6af638dc6c7f72ef3481a718769fd/comfy_extras/nodes_mesh_postprocess.py
* REST routes: https://github.com/Comfy-Org/ComfyUI/blob/7a28332047b6af638dc6c7f72ef3481a718769fd/server.py

The announcement directs users to ComfyUI **0.34.0** and says these integrations
remove custom compiled CUDA extensions and reimplement postprocessing in
PyTorch/SciPy. This is **not removal of PyTorch's device/runtime requirements**.
The preflight uses capability checks rather than assuming a version string is
sufficient; the exact reference commits above are the inspected interface.

Core has `Trellis2Conditioning`, `Pixal3DConditioning`, `Trellis2ShapeStage`,
`Trellis2UpsampleStage`, `Trellis2TextureStage`, and native VAE decoders.
Crucially, Pixal3D's UI label `fov` is the API input **`camera_angle_x`**, whereas
`Pixal3DMultiViewConditioning` uses `fov`. Display names are not API keys.
`Trellis2ShapeStage` accepts positive/negative conditioning and a `VOXEL`, and
returns two conditioning outputs plus a latent. Native postprocess includes
`DecimateMesh`, `RemeshMesh`, `UnwrapMesh`, `BakeTextureFromVoxel`, normal and AO
baking, and texture application. None of this proves compatibility with the
legacy custom workflow's overrides or Remesher's file-history parser.

The packaged `native_inventory.json` was derived from the pinned editor graph:
unique node types excluding `Note`/`MarkdownNote`, and unique
`properties.models` directory/name pairs. It is inventory metadata, not an
executable workflow or model downloader. It requires:

| Directory | Exact filename |
| --- | --- |
| diffusion_models | trellis_2_int8_convrot.safetensors |
| diffusion_models | pixal3d_int8_convrot.safetensors |
| vae | trellis_2_shape_vae_bf16.safetensors |
| vae | trellis_2_texture_vae_bf16.safetensors |
| clip_vision | dino_v3_L_naf_fp32.safetensors |
| background_removal | birefnet.safetensors |
| geometry_estimation | moge_2_vitl_normal_fp16.safetensors |

Official weight repositories: https://huggingface.co/Comfy-Org/TRELLIS.2,
https://huggingface.co/Comfy-Org/Pixal3D,
https://huggingface.co/Comfy-Org/BiRefNet,
https://huggingface.co/Comfy-Org/MoGe.
The Pixal3D multiview tutorial specifies a **different** diffusion model:
`pixal3d_multiview_int8_convrot.safetensors`. That workflow is outside this
inventory. Native multiview is real upstream functionality, but is not validated
as equivalent to Remesher's existing behavior. Generation also does not provide
skeleton generation, skinning, retargeting, or animation parity automatically.

## Hardware evidence, not inference from the word “native”

Source inspection shows sparse operations implemented with torch tensors,
`searchsorted`, integer indexing and chunked matrix operations, with device and
memory selection delegated to ComfyUI. Mesh postprocessing imports SciPy sparse,
spatial and ndimage functions. These remove extension build obstacles; they do
not establish every dtype, quantization kernel or operation on every device.

| Target | Evidence in this change | Generation status |
| --- | --- | --- |
| Spark / Linux ARM64 / GB10 | Python tests and loopback HTTP protocol tests run on host `spark`; `uname -m` = `aarch64`; `nvidia-smi` = NVIDIA GB10, driver 580.173.02 | Not tested |
| CPU | Source uses PyTorch/SciPy; no model execution | Not validated |
| Apple MPS | No MPS host or stage execution | Not validated |
| AMD ROCm | No ROCm host or stage execution | Not validated |

The existing Spark endpoint on port 8188 was unavailable to this preflight.
No ComfyUI or torch install, model download, native server launch, or generation
was attempted. Local ARM64 tests are **client validation only**, not native 3D
hardware certification. CI/CD promotion must wait for native ARM64/Spark
acceptance; this change does not modify CI or Docker.

## Next slice: explicit local runtime and acceptance gates

Keep `server_url`/legacy defaults. Add a separate opt-in `native-local` runtime
configuration: absolute existing Python executable, absolute existing ComfyUI
checkout, private input/output/user directories, loopback port, and explicit
device policy. No automatic environment creation, dependencies or model fetches.

A foreground owner should launch an argv list (no shell), use `--listen
127.0.0.1`, `--disable-all-custom-nodes`, and dedicated directory flags verified
against the pinned CLI. Never attach to a busy port or treat another server's
health response as proof of child readiness. Require both owned child liveness
and the intended server identity. Startup failure, cancellation and shutdown
must terminate only the owned process/group, with bounded wait/escalation. Avoid
PID files as kill authority and never use `pkill` or system-wide interruption.
Test this lifecycle with real disposable processes before launching ComfyUI.

Then export and inspect a minimal single-image **API** graph from the pinned
native installation, validate all inputs/outputs against live `object_info`,
map user overrides by backend (fail unsupported ones), and verify `/history`
GLB discovery plus path-safe artifact download. Test structure sampling, shape
sampling/decoding, texture sampling/decoding, postprocess/UV/PBR and GLB export
separately on Spark; record Python/torch/device/dtype/model hashes, memory,
timing and output files. Repeat that stage matrix independently for CPU, MPS or
ROCm before claiming support. Only then connect native generation to the CLI or
consider default changes. Existing rigging/animation tests remain separate gates.
