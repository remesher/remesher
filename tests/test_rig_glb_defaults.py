import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _mia_auto_rig_inputs():
    workflow = json.loads((ROOT / "examples" / "rig_glb_mia.json").read_text())
    nodes = [node for node in workflow.values() if node.get("class_type") == "MIAAutoRig"]
    assert len(nodes) == 1
    return nodes[0]["inputs"]


def test_default_mia_rig_workflow_preserves_textures():
    inputs = _mia_auto_rig_inputs()
    assert inputs["embed_textures"] is True
    # 50k triggered MIA's destructive simplification/serialization path in the
    # texture regression: materials/images/textures and TEXCOORD_0 disappeared.
    # 80k is the validated notebook/demo default for Trellis2-sized GLBs.
    assert inputs["target_face_count"] >= 80000


def test_rig_cli_default_help_mentions_texture_preservation():
    source = (ROOT / "src" / "comfy_prompt_cli" / "__init__.py").read_text()
    assert "default 80000 preserves Trellis textures" in source
    assert "enabled by default to preserve textured GLBs" in source
