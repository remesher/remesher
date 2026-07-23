# Remesher Lab

Remesher Lab is a practical workspace for turning text prompts or concept images into rigged 3D character assets. It combines ComfyUI workflows, a Python CLI harness, and repeatable notebook-based experiments so teams can generate meshes, inspect outputs, and iterate toward animation-ready GLB files.

## What the lab demonstrates

- **Prompt or image in:** start from a text prompt, a sketch, or an existing character image.
- **Mesh out:** generate GLB assets through ComfyUI workflows such as Qwen image generation/editing and Trellis-based reconstruction.
- **Rigging pass:** run rigging workflows that produce GLB characters ready for downstream animation tests.
- **Agent-friendly automation:** use the `comfy-prompt-cli` commands and notebooks to submit prompts, stream progress, and download generated artifacts.

## Repository

The lab source is published at [github.com/remesher/remesher](https://github.com/remesher/remesher).

```bash
git clone https://github.com/remesher/remesher.git
cd remesher
uv sync
```

## Prerequisites

- Python with [`uv`](https://docs.astral.sh/uv/)
- A reachable ComfyUI server
- Required ComfyUI nodes and models for the workflows you plan to run, for example:
  - Qwen image generation/edit nodes
  - Trellis/Trellis2 mesh generation nodes
  - Rigging nodes and model assets used by the included rigging workflow

Initialize the CLI configuration with your ComfyUI endpoint:

```bash
uv run comfy-prompt-cli config init --force
```

`config.json` should point at your ComfyUI server:

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
  --target-face-num 800000 \
  --filename-prefix wrestler_mesh \
  --texture-seed 67890 \
  --out-dir downloads/lab
```

### 5. Rig GLB

Run the rigging workflow on a generated mesh:

```bash
uv run comfy-prompt-cli rig-glb \
  --mesh downloads/lab/wrestler_mesh.glb \
  --glb-name wrestler_rigged \
  --out-dir downloads/lab
```

### 6. End-to-end text to rigged GLB

For a single-pass smoke test, generate and rig from one prompt:

```bash
uv run comfy-prompt-cli text-to-rigged-glb \
  --prompt "A stylized game-ready wrestler, full body, neutral pose" \
  --out-dir downloads/lab-smoke
```

## Included lab assets

- `notebooks/01_comfy3d_remesher_cli.ipynb` — CLI-driven ComfyUI generation and download workflow.
- `notebooks/02_sketch_qwen_edit_to_rigged_kick.ipynb` — sketch/image edit through rigged character iteration.
- `notebooks/03_upload_image_and_mixamo_retarget.ipynb` — image upload and retargeting experiments.
- `notebooks/04_ollama_gemma_pidev.ipynb` — local model/tooling exploration for agent-assisted iteration.
- `examples/` — ComfyUI API prompt JSON templates for generation, reconstruction, and rigging.

## Output expectations

A successful lab run should produce:

- Generated preview images from text or image-edit prompts.
- One or more `.glb` mesh outputs.
- A rigged `.glb` suitable for animation or retargeting tests.
- Downloaded artifacts under the selected `--out-dir`.

## Troubleshooting

- **Connection errors:** verify `config.json`, ComfyUI host/port, and that the server is reachable from the machine running the CLI.
- **Workflow JSON errors:** use ComfyUI API prompt JSON, not the UI workflow export format with `nodes` and `links`.
- **Missing node/model errors:** install the ComfyUI custom nodes and model weights required by the selected workflow.
- **No GLB output:** inspect the ComfyUI prompt history for the submitted prompt ID and confirm the workflow writes a `.glb` artifact.
- **Large artifacts:** reduce target face count or texture size when moving outputs through size-limited channels.

## Contributing lab notes

Update this file when the lab workflow changes. The website page at [remesher.com/lab](https://remesher.com/lab) is designed to load this Markdown from the repository so the public lab guide stays close to the executable examples.
