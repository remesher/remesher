---
name: remesher-cli
description: Operate the Remesher comfy-prompt-cli against a Comfy3D ComfyUI endpoint: health checks, text/image generation, image-to-GLB, rigging, and downloads.
version: 0.1.0
---

# Remesher CLI Skill

Use this skill when an agent needs to operate the Remesher Typer CLI in this repository.

## Environment

- Repo path inside demo container: `/workspace/remesher`
- Shared uploads: `/workspace/input`
- Shared downloads: `/workspace/output`
- Config file: `/workspace/remesher/config.json`
- Default ComfyUI URL from Jupyter container to sibling Docker container: `http://host.docker.internal:8188/`

## First checks

```bash
cd /workspace/remesher
comfy-prompt-cli --help
comfy-prompt-cli health --config config.json
```

## Common commands

Text to image:
```bash
comfy-prompt-cli text-to-image --config config.json --prompt "A stylized full-body robot character, neutral pose" --out-dir /workspace/output/images
```

Image to GLB:
```bash
comfy-prompt-cli image-to-glb --config config.json --image /workspace/input/character.png --target-face-num 80000 --filename-prefix demo_character --out-dir /workspace/output/glbs
```

Rig a GLB:
```bash
comfy-prompt-cli rig-glb --config config.json --mesh /workspace/input/character.glb --glb-name demo_character_rigged --out-dir /workspace/output/rigged
```

Text to rigged GLB:
```bash
comfy-prompt-cli text-to-rigged-glb --config config.json --prompt "A stylized wrestler character, full body, neutral pose" --target-face-num 80000 --out-dir /workspace/output/text_to_rigged
```

## Validation rules

- Always run `comfy-prompt-cli health` before submitting heavy workflows.
- Assert generated files exist and are non-empty with `test -s`.
- Save outputs under `/workspace/output` so the Jupyter file browser can download them.
- If ComfyUI rejects a workflow, inspect `/object_info` and container logs before retrying blindly.
- For rig quality demos, render stress poses and classify good/bad based on visible hip/pelvis slivers, tearing, missing limbs, or mesh explosions.
