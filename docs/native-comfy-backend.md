# Optional native ComfyUI backend

## Decision and current scope

The legacy **Comfy3D backend remains the default**. `image-to-glb` now also has
explicit experimental `--backend native` (existing loopback server) and
`--backend native-local` (owned foreground child) routes. These call a real
API-format native graph, upload an image, submit `/prompt`, poll the submitted
ID's `/history`, and retrieve `SaveGLB`'s `3d` artifacts through `/view`.
There is no fallback to Comfy3D on native failure.

The implementation is **not GPU generation certification**. Process lifecycle,
installed CLI dispatch and HTTP/artifact handling are tested with disposable
processes and explicitly labeled protocol fixtures. Successful fixture downloads
do not demonstrate inference or output quality. Native stage execution on Spark
and CPU/MPS/ROCm remains a separate acceptance gate.

No models, packages, environments, or GPU resources are implicitly provisioned.
The [agent setup CLI](native-setup.md) can explicitly provision a pinned TRELLIS
core runtime with separate install/download opt-ins, or reuse existing paths.
Its saved config feeds the owned launcher without reconstructing path flags.
The old read-only preflight remains available independently; its combined-editor
inventory is broader than the minimal generation graph and is not used as a
misleading generation-success signal.

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
GPU inference probe. Custom nodes can shadow core names on an operator-managed
server; the `native-local` launcher disables them for its own child.

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

In the initial preflight investigation the Spark endpoint on port 8188 was
unavailable. That investigation did not install dependencies, fetch weights,
launch native ComfyUI, or generate a mesh. The added lifecycle/protocol tests
are still **client validation only**, not native 3D hardware certification.
CI/CD promotion must wait for native ARM64/Spark acceptance; this change does
not modify CI or Docker.

## Experimental generation and owned launcher

Existing trusted local server (custom nodes may shadow names; the operator owns
its configuration and cancellation):

```sh
comfy-prompt-cli image-to-glb --backend native \
  --native-server http://127.0.0.1:8188 --image prepared-object.png \
  --mesh-seed 42 --texture-seed 43 --target-face-num 80000 --out-dir downloads
```

Owned local server (replace the explicit absolute paths with existing resources):

```sh
comfy-prompt-cli image-to-glb --backend native-local \
  --native-python /absolute/venv/bin/python \
  --native-checkout /absolute/ComfyUI --native-runs ./native-runs \
  --native-device cuda --image prepared-object.png --out-dir downloads
```

`native-local` currently requires POSIX and the main thread. It starts an argv
list, no shell, on numeric loopback, with custom and partner/API nodes disabled.
Input/output/temp/user directories are private to a unique run. Model discovery
uses the explicitly selected checkout's existing model configuration unless
`--native-models` or `--native-config` supplies an explicit model root through a
private extra-model-paths config. The launcher
does not create a model directory, run pip, download weights or copy secrets.
`--native-port 0` selects an unused port; explicit occupied ports are rejected.
Readiness requires both child liveness and exact `/system_stats.system.argv`
identity (including the unique directories), so a bind race cannot silently
attach to another listener. This identity check is not authentication against a
malicious local process. Startup timeout is configurable.

Normal return, exceptions, Ctrl-C and SIGTERM terminate only the owned process
group, with TERM then bounded KILL escalation and child reaping. SIGKILL or host
failure cannot run Python cleanup. Logs and runtime files are retained under the
printed run directory for diagnosis; remove those directories yourself when no
longer needed. The server is not daemonized and does not survive the command.
No PID file, `pkill`, global `/interrupt` or unrelated-server termination is used.
For an existing `native` server, a client timeout leaves the job under operator
control; inspect the reported prompt ID. Poll deadlines do not preempt an in-flight
HTTP operation (30-second inactivity timeout).

### Exact workflow scope

Use `image-to-glb --backend native-local --native-config /absolute/setup.json
--image /absolute/prepared.png --no-decimation` to export the generated geometry
without the `DecimateMesh` node or any face/vertex cap. The decoded shape feeds
UV unwrap directly; texture baking and PBR GLB export are retained. This is an
opt-in for native/native-local only; legacy rejects it. The default remains the
80,000-face simplification target. With no-decimation, an otherwise valid
`--target-face-num` value has no effect. Generation resolution, seeds, sampler
settings, UV weld distance and atlas resolution are unchanged. This is not a
watertightness/quality guarantee; UV unwrapping still welds/splits seam vertices.
Larger meshes increase memory use, UV processing time and file size.

Opt-in `--mesh-repair fill|solid` runs native Torch/SciPy repair before UV/PBR,
requires `--no-decimation`, and adds no NVIDIA-only dependencies. See
[portable repair settings and limitations](native-portable-repair.md) and
[actual wrestler stage evidence](portable-repair-wrestler-acceptance.md).

`examples/img_to_native_trellis2.json` is a plain API-format example;
`native_backend.build_prompt` builds the equivalent graph and maps native
image/seed/face-count/prefix overrides. The source interfaces were rechecked at
`7a28332047b6af638dc6c7f72ef3481a718769fd`, including `nodes_custom_sampler.py`
(`CFGOverride`), `nodes_save_3d.py` (`SaveGLB`), `_io.py` (dynamic combo wire values)
and `_ui.py` (`Saved3DModels` emits **`3d`**, not a legacy files key).

The bounded preset is **512-resolution shape / 1024 texture atlas**:
DINO conditioning → structure sampling/decoding → shape sampling/decoding →
texture sampling/decoding → midpoint decimation → UV unwrap → base-color,
metallic and roughness bake → texture attachment → SaveGLB. It deliberately
omits the official editor's 1536 upsample, remesh, AO and normal-map branches.
Supply a clean, cropped object image; automatic background removal/cropping and
MoGe estimation are not included. `--subject-scale` padding still applies before
upload if explicitly requested.

`--native-model pixal3d --native-camera-angle 49.13` selects the single-image
Pixal3D branch; the API input is `camera_angle_x`, not its `fov` display label.
The default is `trellis2`. Native uses its own graph and rejects a custom legacy
`--workflow-file`; the legacy `config.json`/server defaults are not changed.
This preset requires only its selected diffusion model, DINO, and both VAEs
from the table above, not the unselected diffusion model, BiRefNet or MoGe.

Before upload/queue, `/object_info` checks required keys, link slot/types, numeric
bounds, enums/model filenames and dynamic option keys. LoadImage's existing-file
enum is intentionally deferred until after upload to ComfyUI's own `/prompt`
validation. Model presence is not a content/hash or hardware check. Missing
capabilities fail explicitly, with no backend substitution. Download handling
only reads the graph's SaveGLB `3d` output, rejects traversal/non-output references,
uses fresh local filenames (no overwrite), streams at most 512 MiB per file and
checks GLB v2 magic/version/declared length. This is transport integrity, not mesh
quality or geometry validation.

### Remaining acceptance gates

Run actual native structure, shape, texture, postprocess/UV/PBR and export on
Spark, retaining Python/torch/device/dtype/model hashes, timing/memory, server
history and generated mesh inspection. Repeat independently for CPU, MPS or
ROCm before claiming hardware support. The absence of custom CUDA extensions
alone is insufficient. Rigging, skinning, retargeting and animation parity remain
separate gates; existing Comfy3D workflows and tests are preserved.
