# Experimental SkinTokens rigging

MIA remains the default rigging backend. SkinTokens is opt-in and is not GPU-
validated by the CLI protocol tests. No model, runtime, or weights are installed
by these commands.

```sh
uv run comfy-prompt-cli rig-glb --rigging-backend skintokens \
  --mesh character.glb --glb-name character_skintokens --out-dir downloads

uv run comfy-prompt-cli text-to-rigged-glb --prompt "a robot in a T pose" \
  --rigging-backend skintokens --num-beams 10
```

An existing local mesh is uploaded using the existing ComfyUI upload path. A
non-local `--mesh` is passed as a server-accessible GLB reference: relative paths
are relative to ComfyUI's input directory, not the CLI working directory. The
node permits absolute paths only inside the server's input/output/temp roots.
The end-to-end command downloads and re-uploads its generated GLB before rigging.

## Parameters

Both rig commands accept:

| Option | Default | Node input |
| --- | --- | --- |
| `--rigging-backend` | `mia` | Select `mia` or `skintokens` |
| `--use-skeleton / --no-use-skeleton` | false | `use_skeleton` |
| `--use-transfer / --no-use-transfer` | true | `use_transfer` |
| `--use-postprocess / --no-use-postprocess` | false | `use_postprocess` |
| `--num-beams` | 10, range 1–20 | `num_beams` |
| `--glb-name` | input/generated GLB stem | `output_name`, with `.glb` appended if absent |

Choose a new output name for repeated inference: the node refuses to overwrite
an existing server output. Relative subdirectories are allowed; absolute output
paths and traversal are rejected. `--seed` on `text-to-rigged-glb` remains the
image-generation seed. SkinTokens does not expose an inference seed.

The built-in single-node graph works without a workflow file in the current
working directory. An editable API graph is provided in
`examples/rig_glb_skintokens.json`. Use `--workflow-file` with `rig-glb`, or
`--rig-workflow-file` with `text-to-rigged-glb`. Custom graphs must contain
`SkinTokensRigGLB`; CLI parameter defaults/overrides are applied to that node.
Without `--mesh`, `rig-glb` can read `glb_path` from the custom graph.

MIA-only controls (`--no-fingers`, `--use-normal`, `--reset-to-rest`,
`--target-face-count`, `--embed-textures`, `--precision`, `--attn-backend`, and
Blender auto-skin controls) do not apply to SkinTokens. In particular, the legacy
`--auto-skin` default does **not** replace SkinTokens weights. MIA's existing
workflow and automatic-weight defaults are unchanged.

## Server integration contract

Install the sibling ComfyUI-UniRig fork with `SkinTokensRigGLB` and configure its
separate SkinTokens runtime as described in that fork's `docs/skintokens.md`.
The CLI requires:

- Required STRING inputs `glb_path` and `output_name`.
- Optional inputs `use_skeleton=false`, `use_transfer=true`,
  `use_postprocess=false`, `num_beams=10` (integer, range 1–20).
- A STRING result path for downstream nodes and a downloadable `ui.files` entry
  containing `filename`, `subfolder`, and `type: "output"`. ComfyUI exposes the
  latter in history outputs; the CLI downloads via `/view`.

A STRING result alone does not establish a downloadable artifact. Missing GLBs
and server execution failures return nonzero; they are not reported as success.

The sibling node and upstream inference interface do not support `seed`.
The CLI neither accepts a rig seed option nor emits a SkinTokens seed input.
Remove any stale `seed` input from a custom SkinTokens workflow; the CLI rejects
it rather than silently implying reproducibility. Seeds on other nodes and
existing image/mesh/texture generation controls are unchanged.

## Retargeting boundary and validation

SkinTokens generic bone names are not Mixamo semantic names. This integration
ends at the rigged GLB; it does not invent a semantic mapping or rename bones by
index. The ARP worker rejects targets without `mixamorig:Hips` before importing
the animation or building its same-name mapping. Automatic Mixamo retargeting of
generic SkinTokens output is unsupported until an explicit mapping is validated.
An existing supplied skeleton does not, by itself, certify retarget compatibility.

Tests cover CLI/help, workflow fields, upload dispatch, end-to-end stage routing,
legacy defaults, parameter rejection, and real HTTP submission/history/download
against a local protocol fixture. Fixture bytes are not model output. GPU rig
quality, skinning, textures, topology, runtime setup and
animation require separate real-server/asset acceptance.
