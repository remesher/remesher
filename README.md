# comfy-prompt-cli

A small Typer CLI to submit ComfyUI API prompts, poll async completion, and download generated `.glb` outputs.

---

## What it does

- Reads ComfyUI server URL from `config.json`
- Submits prompt JSON to `POST /prompt`
- Supports runtime overrides for key fields:
  - positive text prompt
  - mesh seed
  - target face count
  - file name prefix
  - texture seed
- Waits for prompt completion by polling:
  - `GET /queue`
  - `GET /history/{prompt_id}`
- Auto-downloads `.glb` output via `GET /view`

---

## Requirements

- Python + [`uv`](https://docs.astral.sh/uv/)
- ComfyUI server reachable from this machine
- A ComfyUI build with required nodes/models installed and running at `server_url`, such as:
  - [`michaelgold/comfy3d`](https://github.com/michaelgold/comfy3d), or
  - another ComfyUI setup that includes **qwen-image-2512** and **Trellis2**

---

## Quick start

```bash
cd /Users/mg/.openclaw/workspace/comfy-prompt-cli
uv sync
uv run comfy-prompt-cli config init --force
```

Default `config.json`:

```json
{
  "server_url": "http://localhost:8188/"
}
```

---

## Commands

### 1) Health check

```bash
uv run comfy-prompt-cli health
```

### 2) Text to image (qwen_image_2512)

```bash
uv run comfy-prompt-cli text-to-image \
  --prompt "A cinematic portrait of a fox in rain"
```

### 3) Image + text to image (qwen_image_edit_2511)

```bash
uv run comfy-prompt-cli image-text-to-image \
  --image path/to/input.png \
  --prompt "Put this character in a futuristic city at sunset"
```

### 4) Image to GLB (img_to_trellis2)

```bash
uv run comfy-prompt-cli image-to-glb \
  --image path/to/input.png \
  --mesh-seed 12345 \
  --target-face-num 800000 \
  --filename-prefix my_mesh \
  --texture-seed 67890
```

### 5) Submit prompt JSON

```bash
uv run comfy-prompt-cli send path/to/prompt_api.json
```

### 6) Submit with overrides

```bash
uv run comfy-prompt-cli send path/to/prompt_api.json \
  --prompt "A 3d cartoon astronaut in a t-pose" \
  --mesh-seed 12345 \
  --target-face-num 800000 \
  --filename-prefix astronaut \
  --texture-seed 67890
```

### 7) Wait for completion + download GLB

```bash
uv run comfy-prompt-cli wait <prompt_id> --out-dir downloads
```

### 8) One-shot full pass (submit + wait + download)

```bash
uv run comfy-prompt-cli run path/to/prompt_api.json \
  --prompt "A 3d cartoon astronaut in a t-pose" \
  --mesh-seed 12345 \
  --target-face-num 800000 \
  --filename-prefix astronaut \
  --texture-seed 67890 \
  --out-dir downloads
```

### 9) Dry run (build payload only)

```bash
uv run comfy-prompt-cli send path/to/prompt_api.json --dry-run
```

---

## Typical workflow

```bash
# Text -> image
uv run comfy-prompt-cli text-to-image --prompt "A 3d cartoon astronaut in a t-pose"

# Image + text -> image
uv run comfy-prompt-cli image-text-to-image \
  --image path/to/input.png \
  --prompt "Make this look like a fashion editorial"

# Image -> GLB
uv run comfy-prompt-cli image-to-glb \
  --image path/to/input.png \
  --mesh-seed 12345 \
  --target-face-num 800000 \
  --filename-prefix astronaut \
  --texture-seed 67890
```

---

## Input format notes

`send` expects **ComfyUI API prompt JSON**.

Accepted:
- direct API prompt object (`{"node_id": {...}}`), or
- wrapper with top-level `prompt` key (`{"prompt": {...}}`)

Rejected:
- UI workflow export format with top-level `nodes` + `links`

If you pass workflow export JSON, CLI will show a clear error telling you to export/copy API prompt JSON.

Image-based commands (`image-text-to-image`, `image-to-glb`) accept a local image path.
The CLI uploads that image to ComfyUI input storage before submitting the workflow.

---

## Examples included

- `examples/qwen_image_2512.json`  
  Text-to-image API prompt workflow
- `examples/qwen_image_edit_2511.json`  
  Image+text editing API prompt workflow
- `examples/img_to_trellis2.json`  
  Image-to-GLB API prompt workflow
- `examples/qwen_to_trellis2.json`  
  Text-to-GLB workflow template

---

## Troubleshooting

- **Connection error**: verify `config.json` `server_url`, host reachability, and ComfyUI port.
- **Upload error for image commands**: verify your image path exists and ComfyUI supports `POST /upload/image`.
- **No GLB found**: workflow may not output `.glb`; check `/history/{prompt_id}` outputs.
- **Large GLB can’t be sent over Telegram**: Telegram may reject with `413 Request Entity Too Large`; use local path or reduce mesh/texture settings.
