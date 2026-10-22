import pytest

from comfy_prompt_cli.native_backend import build_prompt


@pytest.mark.parametrize('model', ['trellis2', 'pixal3d'])
def test_final_export_has_smooth_normals_after_material_application(model):
    graph = build_prompt('input.png', model=model)
    assert graph['save']['inputs']['mesh'] == ['smooth_normals', 0]
    assert graph['smooth_normals'] == {
        'class_type': 'MeshSmoothNormals',
        'inputs': {'mesh': ['textured', 0], 'crease_angle': 180.0},
    }
    assert graph['textured']['inputs']['mesh'] == ['unwrap', 0]
