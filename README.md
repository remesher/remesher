# remesher

An agent harness that uses a small Typer CLI to submit ComfyUI API prompts, stream async progress via WebSocket, and download generated outputs.

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
- Streams progress via `GET /ws?clientId=...` when a client ID is available
- Waits for completion using `GET /history/{prompt_id}` (with queue polling fallback)
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

### T-pose safe framing

For strict T-pose characters, keep every fingertip visible with roughly 15–20% empty margin beyond each hand. Create a deterministic 65% centered resize on a white square canvas:

```bash
uv run comfy-prompt-cli pad-tpose-image \
  --image path/to/tpose.png \
  --subject-scale 0.65 \
  --output downloads/tpose_padded.png
```

Or apply the same preprocessing directly before `image-to-glb`:

```bash
uv run comfy-prompt-cli image-to-glb \
  --image path/to/tpose.png \
  --subject-scale 0.65
```

`image-to-glb` defaults to `--subject-scale 1.0`, preserving existing behavior unless padding is requested.

### 4) Image to GLB (img_to_trellis2)

```bash
uv run comfy-prompt-cli image-to-glb \
  --image path/to/input.png \
  --mesh-seed 12345 \
  --target-face-num 80000 \
  --filename-prefix my_mesh \
  --texture-seed 67890
```

### 5) Rig GLB (rig_glb_mia)

```bash
uv run comfy-prompt-cli rig-glb \
  --mesh wrestler_multi_trellis.glb \
  --glb-name rigged
```

By default, `rig-glb` uses MIA to create the humanoid armature, then runs an
isolated Blender post-stage that:

1. merges coincident triangle vertices (`1e-6` by default),
2. removes the MIA skin weights,
3. applies Blender **Armature Deform → With Automatic Weights**,
4. reimports and validates the resulting GLB.

The canonical worker ships inside the `comfy_prompt_cli.workers` package, so
notebook and installed-CLI users get the same first-party implementation without
a source checkout or a worker-path override. It runs directly when local Python
provides `bpy`; the CLI can otherwise execute that same packaged worker in the
configured Comfy3D container.

The expected downloaded filename remains the final auto-skinned GLB. Remesher
also preserves the pre-postprocess MIA artifact as `*.mia_raw.glb` and writes an
`*.autoskin.json` report with weld and weighted/unweighted vertex counts. The
final GLB is published first and the report is published last as the commit
marker; `output_sha256` must match the final GLB before consumers treat the pair
as complete. Neither public artifact is mutated after publication. The pipeline
fails if Blender assigns no weights or leaves more than 0.5% of the
welded vertices unweighted before the nearest-bone completion pass. Before bone
heat, disconnected components of at most 128 vertices are deleted only when
their combined size is no more than 0.5% of the welded mesh.

Use `--no-auto-skin` to keep the previous MIA-weight output unchanged. Advanced
controls include `--auto-skin-weld-distance`, `--max-unweighted-fraction`,
`--auto-skin-worker`, and `--bpy-container`.

### 6) Text to GLB (end-to-end)

```bash
uv run comfy-prompt-cli text-to-glb \
  --prompt "A stylized wrestler character, full body, neutral pose"
```

### 7) Text to Rigged GLB (end-to-end)

```bash
uv run comfy-prompt-cli text-to-rigged-glb \
  --prompt "A stylized wrestler character, full body, neutral pose"
```

`text-to-rigged-glb` uses the same Blender automatic-weight post-stage by
default and supports the same opt-out and tuning flags.

### 8) Submit prompt JSON

```bash
uv run comfy-prompt-cli send path/to/prompt_api.json
```

### 9) Submit with overrides

```bash
uv run comfy-prompt-cli send path/to/prompt_api.json \
  --prompt "A 3d cartoon astronaut in a t-pose" \
  --mesh-seed 12345 \
  --target-face-num 80000 \
  --filename-prefix astronaut \
  --texture-seed 67890
```

### 10) Wait for completion + download GLB

```bash
uv run comfy-prompt-cli wait <prompt_id> --out-dir downloads
```

If you want live `/ws` progress for an already-submitted prompt, pass the same `client_id` used when submitting:

```bash
uv run comfy-prompt-cli wait <prompt_id> --client-id <client_id> --out-dir downloads
```

### 11) One-shot full pass (submit + wait + download)

```bash
uv run comfy-prompt-cli run path/to/prompt_api.json \
  --prompt "A 3d cartoon astronaut in a t-pose" \
  --mesh-seed 12345 \
  --target-face-num 80000 \
  --filename-prefix astronaut \
  --texture-seed 67890 \
  --out-dir downloads
```

### 12) Dry run (build payload only)

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
  --target-face-num 80000 \
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
