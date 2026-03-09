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

### 2) Submit prompt JSON

```bash
uv run comfy-prompt-cli send path/to/prompt_api.json
```

### 3) Submit with overrides

```bash
uv run comfy-prompt-cli send path/to/prompt_api.json \
  --prompt "A 3d cartoon astronaut in a t-pose" \
  --mesh-seed 12345 \
  --target-face-num 800000 \
  --filename-prefix astronaut \
  --texture-seed 67890
```

### 4) Wait for completion + download GLB

```bash
uv run comfy-prompt-cli wait <prompt_id> --out-dir downloads
```

### 5) One-shot full pass (submit + wait + download)

```bash
uv run comfy-prompt-cli run path/to/prompt_api.json \
  --prompt "A 3d cartoon astronaut in a t-pose" \
  --mesh-seed 12345 \
  --target-face-num 800000 \
  --filename-prefix astronaut \
  --texture-seed 67890 \
  --out-dir downloads
```

### 6) Dry run (build payload only)

```bash
uv run comfy-prompt-cli send path/to/prompt_api.json --dry-run
```

---

## Typical workflow

```bash
# Submit
uv run comfy-prompt-cli send examples/qwen_to_trellis2_api---094ad7bb-e041-4d99-8768-50ebaf622e2e.json \
  --prompt "A 3d cartoon astronaut in a t-pose" \
  --mesh-seed 12345 \
  --target-face-num 800000 \
  --filename-prefix astronaut \
  --texture-seed 67890

# Then wait + download
uv run comfy-prompt-cli wait <prompt_id> --out-dir downloads
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

---

## Examples included

- `examples/qwen_to_trellis2---fc8244b7-d5d1-48ac-8913-1e8770cace7a.json`  
  Workflow export example (expected to fail validation for `/prompt`)
- `examples/qwen_to_trellis2_api---094ad7bb-e041-4d99-8768-50ebaf622e2e.json`  
  API prompt example (valid for submission)

---

## Troubleshooting

- **Connection error**: verify `config.json` `server_url`, host reachability, and ComfyUI port.
- **No GLB found**: workflow may not output `.glb`; check `/history/{prompt_id}` outputs.
- **Large GLB can’t be sent over Telegram**: Telegram may reject with `413 Request Entity Too Large`; use local path or reduce mesh/texture settings.
