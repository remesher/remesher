---
name: remesher-cli
description: Operate the Remesher comfy-prompt-cli against a Comfy3D ComfyUI endpoint: health checks, text/image generation, image-to-GLB, rigging, and downloads.
version: 0.1.0
---

# Remesher CLI Skill

Use this skill when an agent needs to operate the Remesher Typer CLI in this repository.

## Native setup (agent/plugin contract)

These commands run on the host; do not assume the demo container paths below.
Use absolute user-approved paths and parse setup stdout as one JSON document.

```sh
comfy-prompt-cli native-setup plan --root /absolute/native-runtime
comfy-prompt-cli native-setup check --config /absolute/native-setup.json
# Only after explicit package and 8,512,567,756-byte core model approval:
comfy-prompt-cli native-setup apply --root /absolute/native-runtime --allow-install --allow-download
comfy-prompt-cli image-to-glb --backend native-local --native-config /absolute/native-runtime/native-setup.json --image /absolute/prepared-object.png --native-preset quality-1536-solid768
```

Exit 0 means plan produced or setup ready, 1 means blockers, 2 means invalid/failed
operation. Inspect `ready`, `blockers`, `memory`, `capabilities`, `checkout`, and
model `verified` fields; never treat `generation_validated=false` as success.
The config object contains schema_version, absolute venv/checkout/models/runs/output,
device (cuda/cpu), and minimum_memory_gib. Save only plan's `config` object when
customizing existing paths. Reuse does not authorize modifying an unmanaged venv.
Conflicting runtime flags with `--native-config` fail; generation controls such
as seeds/timeout remain explicit. Model visibility is configured per owned child.

Never raise or escape cgroup limits silently: insufficient effective memory means
obtain approval for a sufficiently sized bounded scope, then re-check. The
invocation-only low-memory override acknowledges risk and does not raise limits.
Model downloads resume/reuse only after exact size/SHA256 verification; no generic
URLs or manifest overrides. Both native models have single-image acceptance;
quality remains provisional. Recommend the explicit quality preset (1536 shape,
solid768, atlas4096, no decimation or precluster cap, smooth normals) only with
approval for its resource cost. Use `--native-preset fast` for a bounded smoke;
omitting a preset preserves old defaults. Presets reject contradictory flags.
See `docs/native-setup.md` for the
complete executable plugin contract, isolation limits, and acceptance task index.

## Fixed-mesh export verification

For shading/export-only changes, do not regenerate or re-unwrap the asset.
Run `scripts/verify-native-normals.py` with the existing native runtime Python,
installed CLI wheel, pinned checkout and immutable final GLB into a new output
directory. It runs the candidate's normal node and SaveGLB serializer on CPU,
then checks actual NORMAL accessors, unit/finite values and exact positions,
indices, UVs, material JSON and texture pixels. Compare textured and gray
front/rear/side renders that actually consume exported normals. This is export
acceptance, not new model inference or topology/manifold certification.

## Environment (legacy demo container only)

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
