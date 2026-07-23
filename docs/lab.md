# Remesher Lab

Remesher Lab is a practical workspace for turning text prompts or concept images into rigged 3D character assets. It combines ComfyUI workflows, a Python CLI harness, and repeatable notebook-based experiments so teams can generate meshes, inspect outputs, and iterate toward animation-ready GLB files.

## What the lab demonstrates

- **Prompt or image in:** start from a text prompt, a sketch, or an existing character image.
- **Mesh out:** generate GLB assets through ComfyUI workflows such as Qwen image generation/editing and Trellis-based reconstruction.
- **Rigging pass:** run rigging workflows that produce GLB characters ready for downstream animation tests.
- **Agent-friendly automation:** use the `comfy-prompt-cli` commands and notebooks to submit prompts, stream progress, and download generated artifacts.

## Launch the RunPod lab template

The fastest way to run the lab is to launch the prepared RunPod template:

[Launch the Remesher RunPod template](https://console.runpod.io/deploy?template=oly10k0o6g&ref=74ihrngg)

The template starts the Remesher notebook/control environment. It is designed to provide JupyterLab and the Remesher CLI, then let the notebooks pull and run the separate `michaelgold/comfy3d` runtime container.

### RunPod launch steps

1. Open the template link above while signed in to RunPod.
2. Choose a GPU pod with enough VRAM for the workflow you plan to run. Image generation and GLB reconstruction are GPU-heavy; if a workflow fails with out-of-memory errors, stop the pod and relaunch with a larger GPU.
3. Attach or create persistent storage if you want models and generated assets to survive pod restarts. The image uses `/workspace` as the default workspace and may use `/runpod-volume` when a RunPod volume is attached.
4. Deploy the pod and wait for it to finish booting.
5. Open the pod's JupyterLab endpoint on port `8888`.
6. In JupyterLab, browse to `/workspace/remesher/notebooks`.
7. Start with `01_comfy3d_remesher_cli.ipynb` unless you specifically want one of the later labs.
8. If the notebook asks for a Hugging Face token, paste a **read** token. DINOv3 and other gated assets require that token and may also require requesting model access on Hugging Face.
9. Run the notebook cells from top to bottom. The setup cells configure `config.json`, pull/start Comfy3D, download or verify the required models, and run `comfy-prompt-cli health` before the heavier generation steps.

### What the RunPod image provides

- JupyterLab on port `8888`.
- Remesher notebooks staged under `/workspace/remesher/notebooks`.
- Helper scripts under `/workspace/remesher/docker/demo-jupyter/scripts`.
- The Remesher CLI installed in the image environment.
- Docker CLI/Python Docker SDK support so notebooks can pull and run `michaelgold/comfy3d`.
- Optional Ollama/Gemma setup scripts for Lab 4.

### Important RunPod notes

- The lab image is a notebook/control image, not the Comfy3D runtime itself. The notebooks start Comfy3D separately.
- The ComfyUI API endpoint used by the notebooks is `http://host.docker.internal:8188/`.
- Starting Comfy3D from the notebooks requires Docker daemon access, usually a mounted `/var/run/docker.sock`. The image
  includes the Docker CLI, but the pod/template must provide the daemon socket.
- Generated files are written under `/workspace/output` by default.
- Uploaded inputs should go under `/workspace/input` or use the upload widget in Lab 3.
- Protected Hugging Face downloads require `HF_TOKEN` in the notebook/session environment.
- Large first runs can take a while because model downloads and container pulls are cached only after they complete once.

## Repository

The lab source is published at [github.com/remesher/remesher](https://github.com/remesher/remesher).

```bash
git clone https://github.com/remesher/remesher.git
cd remesher
uv sync
```

## Prerequisites

If you launch from the RunPod template, most software prerequisites are already staged in the image. You still need:

- A RunPod account and a running pod from the lab template.
- A Hugging Face read token for gated model downloads.
- Access approval for gated models such as DINOv3 when required.
- Enough persistent storage for models and generated assets.

For local development, install:

- Python with [`uv`](https://docs.astral.sh/uv/)
- Docker with GPU access if you want the notebooks to start the Comfy3D container locally
- A reachable ComfyUI server
- Required ComfyUI nodes and models for the workflows you plan to run, for example:
  - Qwen image generation/edit nodes
  - Trellis/Trellis2 mesh generation nodes
  - Rigging nodes and model assets used by the included rigging workflow

Initialize the CLI configuration with your ComfyUI endpoint:

```bash
uv run comfy-prompt-cli config init --force
```

`config.json` should point at your ComfyUI server. In the RunPod notebooks this is usually:

```json
{
  "server_url": "http://host.docker.internal:8188/"
}
```

For a local ComfyUI process, use:

```json
{
  "server_url": "http://localhost:8188/"
}
```

## Core workflow

### 1. Health check

Confirm the CLI can reach ComfyUI:

```bash
uv run comfy-prompt-cli health
```

### 2. Text to image

Generate a concept image from a prompt:

```bash
uv run comfy-prompt-cli text-to-image \
  --prompt "A stylized full-body wrestler character, neutral pose"
```

### 3. Image edit

Use an existing sketch or concept image and revise it with text instructions:

```bash
uv run comfy-prompt-cli image-text-to-image \
  --image workspace/input/demo/pencil_sketch_character.jpg \
  --prompt "Make this a bold comic-book wrestler while preserving the silhouette"
```

### 4. Image to GLB

Convert a concept image into a textured mesh:

```bash
uv run comfy-prompt-cli image-to-glb \
  --image path/to/concept.png \
  --mesh-seed 12345 \
  --target-face-num 80000 \
  --filename-prefix wrestler_mesh \
  --texture-seed 67890 \
  --out-dir downloads/lab
```

Use `80000` faces for fast notebook previews. Increase the face count for final exports if you need more detail and the selected GPU has enough memory.

### 5. Rig GLB

Run the rigging workflow on a generated mesh:

```bash
uv run comfy-prompt-cli rig-glb \
  --mesh downloads/lab/wrestler_mesh.glb \
  --glb-name wrestler_rigged \
  --target-face-count 80000 \
  --embed-textures \
  --out-dir downloads/lab
```

### 6. Clean skin weights

The notebooks apply a conservative head/top cleanup after rigging so the head follows the head bone instead of a neutral bone during animation:

```bash
uv run comfy-prompt-cli skin-cleanup-glb \
  --input-glb downloads/lab/wrestler_rigged.glb \
  --output-name wrestler_rigged_headfix \
  --out-dir downloads/lab \
  --mode conservative \
  --repair-zones head_top,head_neck
```

### 7. Retarget animation

Apply a Mixamo FBX animation to a cleaned rigged GLB:

```bash
uv run comfy-prompt-cli retarget-glb \
  --rigged-glb downloads/lab/wrestler_rigged_headfix.glb \
  --animation workspace/input/animation_templates/mixamo/Mma_Kick.fbx \
  --glb-name wrestler_kick \
  --out-dir downloads/lab
```

### 8. End-to-end text to rigged GLB

For a single-pass smoke test, generate and rig from one prompt:

```bash
uv run comfy-prompt-cli text-to-rigged-glb \
  --prompt "A stylized game-ready wrestler, full body, neutral pose" \
  --out-dir downloads/lab-smoke
```

## Lab 1 — Comfy3D, model setup, and the Remesher CLI

Notebook: `notebooks/01_comfy3d_remesher_cli.ipynb`

Lab 1 is the baseline end-to-end walkthrough. Run it first to confirm the pod, Comfy3D container, model cache, and CLI are working together.

### Goals

- Start from a clean notebook session.
- Configure the Remesher CLI to talk to ComfyUI.
- Pull/start the `michaelgold/comfy3d` runtime container.
- Download or verify the exact model groups used by Remesher examples.
- Run a text-to-image prompt.
- Convert an image into a GLB.
- Rig the GLB, clean skin weights, and apply a Mixamo kick animation.

### Main steps

1. Create `/workspace/input`, `/workspace/output`, and `/workspace/models`.
2. Optionally enter a Hugging Face read token for gated model downloads.
3. Write `config.json` with `http://host.docker.internal:8188/` as the ComfyUI server.
4. Run `docker/demo-jupyter/scripts/pull-comfy3d.sh` to pull/start Comfy3D.
5. Run the Remesher model downloader inside the Comfy3D container. The default model group is `all`; targeted groups include `qwenimage2512`, `qwenimageedit2511`, `trellis2`, `dinov3`, and `mia`.
6. Run `comfy-prompt-cli --help` and `comfy-prompt-cli health --config config.json`.
7. Generate a front-facing full-body character image from the included prompt.
8. Use that image, or an uploaded `/workspace/input/character.png`, as the input to `image-to-glb`.
9. Rig the generated GLB with `rig-glb` and `--embed-textures`.
10. Run conservative `skin-cleanup-glb` for `head_top,head_neck`.
11. Retarget the cleaned rigged GLB with the default `Mma_Kick.fbx` animation.
12. Preview GLB outputs in the notebook with the embedded `<model-viewer>` helper.

### Expected outputs

- Generated image files under `/workspace/output/images`.
- Mesh GLBs under `/workspace/output/glbs`.
- Rigged and head-fixed GLBs under `/workspace/output/rigged`.
- Animated GLBs and retarget summaries under `/workspace/output/comfyui/animated`.

### Tips

- Keep the default `80000` face target for fast previews and smaller notebook downloads.
- If texture preservation fails at a low face count, rerun rigging at a higher face count such as `500000`.
- If the GLB preview does not render inline, use the printed `/files/...` link to open or download the asset.

## Lab 2 — Pencil sketch to edited character, rig, and kick animation

Notebook: `notebooks/02_sketch_qwen_edit_to_rigged_kick.ipynb`

Lab 2 starts from the included pencil sketch and shows how Qwen image editing can turn rough art direction into a clean image-to-3D reference.

### Goals

- Use a source sketch instead of a pure text prompt.
- Preserve pose, silhouette, and full-body framing while changing style.
- Produce a 3D-friendly cartoon character reference image.
- Convert the edited image into a GLB.
- Rig, head-fix, and animate the resulting character.

### Main steps

1. Use `workspace/input/demo/pencil_sketch_character.jpg` as the source image.
2. Review the image-edit prompt, which asks for a centered, full-body, orthographic, 3D cartoon wrestler reference on a plain white background.
3. Run `comfy-prompt-cli image-text-to-image` with the sketch and prompt.
4. Inspect the original sketch and Qwen-edited output side by side.
5. Run `image-to-glb` at the default `80000` target faces.
6. Preview the generated GLB.
7. Run `rig-glb` with `--embed-textures`.
8. Run conservative `skin-cleanup-glb` on the head/top zones.
9. Retarget the cleaned rigged GLB with the default Mixamo `Mma_Kick.fbx` animation.
10. Preview the animated GLB in the notebook.

### Expected outputs

- `sketch_to_cartoon_character*.png` in `/workspace/output/images`.
- `sketch_cartoon_80000*.glb` in `/workspace/output/glbs`.
- Cleaned rigged GLBs in `/workspace/output/rigged`.
- Kick animation GLBs in `/workspace/output/comfyui/animated`.

### Tips

- The image-edit prompt matters. Image-to-3D works best with visible hands, feet, continuous limbs, a neutral/A-pose or T-pose, and generous whitespace around the body.
- Avoid cropped portraits, extreme perspective, overlapping limbs, props crossing the body, and busy backgrounds.
- Use this lab when you want to turn a rough drawing into a production-style character reference before reconstruction.

## Lab 3 — Bring your own image and Mixamo FBX

Notebook: `notebooks/03_upload_image_and_mixamo_retarget.ipynb`

Lab 3 replaces the canned sketch with upload widgets so you can test your own character image and, optionally, your own Mixamo animation FBX.

### Goals

- Upload a custom `.png`, `.jpg`, `.jpeg`, or `.webp` character image.
- Optionally upload a custom `.fbx` animation.
- Use the default Mixamo `Mma_Kick.fbx` if no animation is uploaded.
- Run the same image-to-GLB, rigging, cleanup, and retarget pipeline on user-provided inputs.

### Main steps

1. Run the setup cells to configure `config.json`, start Comfy3D, verify models, and check CLI health.
2. Use the `Browse image` widget to select a character image.
3. Optionally use the `Browse FBX` widget to select a Mixamo animation file.
4. Click **Save uploads**. The notebook saves files under `/workspace/input/uploads`.
5. Preview the uploaded image and confirm which FBX will be used.
6. Run `image-to-glb` with a filename prefix based on the uploaded image name.
7. Run `rig-glb` and conservative head-weight cleanup.
8. Run `retarget-glb` using the uploaded FBX or the default `Mma_Kick.fbx`.
9. Preview and download the animated GLB.

### Expected outputs

- Uploaded source assets under `/workspace/input/uploads`.
- User-image mesh GLBs under `/workspace/output/glbs`.
- Cleaned rigged GLBs under `/workspace/output/rigged`.
- Animated GLBs under `/workspace/output/comfyui/animated`.

### Tips

- Use a single full-body character on a simple background.
- The character should be front-facing, centered, uncropped, and have clearly separated limbs.
- For Mixamo retargeting, prefer a standard Mixamo FBX animation with an expected humanoid skeleton.
- If retargeting fails, first verify that the rigged GLB exists and that the FBX upload path printed by the notebook is correct.

## Lab 4 — Ollama/Gemma, pi.dev, and agent-assisted Remesher CLI use

Notebook: `notebooks/04_ollama_gemma_pidev.ipynb`

Lab 4 explores a local-agent workflow. It starts Ollama, pulls Gemma, installs or checks pi.dev, and points the agent at the Remesher CLI skill file.

### Goals

- Start a local Ollama server in the lab environment.
- Pull or verify the configured Gemma model.
- Prepare pi.dev to operate from `/workspace/remesher`.
- Give the agent a concrete Remesher CLI skill so it can run health checks, inspect inputs, and propose CLI actions.

### Main steps

1. Inspect `/workspace/remesher/skills/remesher-cli/SKILL.md`.
2. Set `OLLAMA_MODEL`, defaulting to `gemma4`.
3. Run `docker/demo-jupyter/scripts/ollama-gemma4.sh`.
4. Confirm Ollama is responding at `http://127.0.0.1:11434/api/tags`.
5. Run `docker/demo-jupyter/scripts/install-pidev.sh` to install or verify pi.dev.
6. Export:
   - `OLLAMA_HOST=http://127.0.0.1:11434`
   - `OLLAMA_MODEL=${OLLAMA_MODEL:-gemma4}`
   - `REMESHER_CLI_SKILL=/workspace/remesher/skills/remesher-cli/SKILL.md`
   - `REMESHER_WORKDIR=/workspace/remesher`
7. Ask pi.dev to use the skill, run `comfy-prompt-cli health --config /workspace/remesher/config.json`, list inputs in `/workspace/input`, ask before running heavy workflows, save outputs under `/workspace/output`, and verify non-empty files.

### Suggested pi.dev prompt

```text
Operate the Remesher CLI using the skill at /workspace/remesher/skills/remesher-cli/SKILL.md.
First run comfy-prompt-cli health --config /workspace/remesher/config.json.
Then list inputs in /workspace/input and ask before running a heavy workflow.
Save outputs under /workspace/output and verify files are non-empty.
```

### Expected outputs

- A running Ollama/Gemma local model endpoint.
- A working pi.dev CLI command or a clear install failure to resolve.
- Agent-driven CLI checks and proposed next actions based on the Remesher CLI skill.

### Tips

- Lab 4 is for agent-assisted operation, not the primary asset pipeline. Run Lab 1 first if you have not verified Comfy3D and the model cache yet.
- Keep agent instructions conservative: health check first, list inputs, ask before heavy jobs, and verify all outputs.
- If Gemma is not needed for the current session, you can skip this lab and use Labs 1–3 directly.

## Included lab assets

- `notebooks/01_comfy3d_remesher_cli.ipynb` — CLI-driven ComfyUI generation, reconstruction, rigging, cleanup, and Mixamo retargeting.
- `notebooks/02_sketch_qwen_edit_to_rigged_kick.ipynb` — pencil sketch through Qwen image edit, GLB reconstruction, rigging, cleanup, and kick animation.
- `notebooks/03_upload_image_and_mixamo_retarget.ipynb` — upload widgets for custom character images and optional Mixamo FBX retargeting.
- `notebooks/04_ollama_gemma_pidev.ipynb` — local Ollama/Gemma and pi.dev exploration for agent-assisted iteration.
- `examples/` — ComfyUI API prompt JSON templates for generation, reconstruction, and rigging.
- `docker/demo-jupyter/scripts/` — helper scripts used by the notebooks for Comfy3D startup, model downloads, Ollama/Gemma setup, skin cleanup, and retargeting.

## Output expectations

A successful lab run should produce:

- Generated preview images from text or image-edit prompts.
- One or more `.glb` mesh outputs.
- A rigged `.glb` suitable for animation or retargeting tests.
- Optional head-fixed/cleaned rigged GLBs.
- Optional animated `.glb` files after Mixamo retargeting.
- Downloaded artifacts under the selected `--out-dir` or `/workspace/output`.

## Troubleshooting

- **Connection errors:** verify `config.json`, ComfyUI host/port, and that the server is reachable from the machine running the CLI.
- **RunPod notebook cannot reach ComfyUI:** confirm the Comfy3D container started from the notebook and that the notebook config uses `http://host.docker.internal:8188/`.
- **`failed to connect to the docker API at unix:///var/run/docker.sock`:** the notebook image has the Docker CLI, but
  this pod was launched without Docker daemon/socket access. Relaunch with a template that mounts
  `/var/run/docker.sock:/var/run/docker.sock`, or start Comfy3D separately and set
  `COMFY3D_SERVER_URL=https://<your-comfy3d-endpoint>/` before running `docker/demo-jupyter/scripts/pull-comfy3d.sh`.
- **Workflow JSON errors:** use ComfyUI API prompt JSON, not the UI workflow export format with `nodes` and `links`.
- **Missing node/model errors:** install the ComfyUI custom nodes and model weights required by the selected workflow.
- **Hugging Face gated model errors:** paste a valid read token starting with `hf_` and request access to gated model repositories before rerunning the downloader.
- **No GLB output:** inspect the ComfyUI prompt history for the submitted prompt ID and confirm the workflow writes a `.glb` artifact.
- **GLB has no textures after rigging:** rerun `rig-glb` with `--embed-textures` and consider increasing `--target-face-count`.
- **Animated head/neck deformation:** run the conservative `skin-cleanup-glb` step for `head_top,head_neck` before retargeting.
- **Large artifacts:** reduce target face count or texture size when moving outputs through size-limited channels.

## Contributing lab notes

Update this file when the lab workflow changes. The website page at [remesher.com/lab](https://remesher.com/lab) is designed to load this Markdown from the repository so the public lab guide stays close to the executable examples.
