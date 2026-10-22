import copy
import pytest
from comfy_prompt_cli.native_backend import build_prompt


def test_official1536_only_adds_two_nodes_and_four_rewires():
    options = dict(model='pixal3d', camera_angle=42.75103780924466,
                   no_decimation=True, mesh_repair='solid')
    baseline = build_prompt('padded.png', **options)
    graph = build_prompt('padded.png', shape_resolution=1536, **options)
    assert graph['shape_upsample'] == {'class_type': 'Trellis2UpsampleStage', 'inputs': {
        'positive': ['shape_stage', 0], 'negative': ['shape_stage', 1],
        'shape_latent': ['shape_sample', 0], 'vae': ['shape_vae', 0], 'target_resolution': 1536}}
    assert graph['shape_refine'] == {'class_type': 'KSampler', 'inputs': {
        'model': ['shape_model', 0], 'positive': ['shape_upsample', 0],
        'negative': ['shape_upsample', 1], 'latent_image': ['shape_upsample', 2],
        'seed': 42, 'steps': 12, 'cfg': 7.5, 'sampler_name': 'euler',
        'scheduler': 'simple', 'denoise': 1.0}}
    expected = copy.deepcopy(baseline)
    expected.update({k: graph[k] for k in ('shape_upsample', 'shape_refine')})
    expected['shape_decode']['inputs']['samples'] = ['shape_refine', 0]
    expected['texture_stage']['inputs'].update(positive=['shape_upsample', 0],
        negative=['shape_upsample', 1], shape_latent=['shape_refine', 0])
    assert graph == expected
    assert build_prompt('padded.png', shape_resolution=512, **options) == baseline


@pytest.mark.parametrize('value', [True, 1024, 1536.0, '1536', None])
def test_reject_invalid_shape_resolution(value):
    with pytest.raises(ValueError, match='shape resolution'):
        build_prompt('x.png', shape_resolution=value)


def test_cli_cascade_routes_and_legacy_rejects(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from comfy_prompt_cli import app, native_backend
    image = tmp_path / 'x.png'
    image.write_bytes(b'input')
    seen = {}
    def generate(*args, **kwargs):
        seen.update(kwargs)
        return []
    monkeypatch.setattr(native_backend, 'generate', generate)
    args = ['image-to-glb', '--image', str(image), '--native-shape-resolution', '1536']
    result = CliRunner().invoke(app, args + ['--backend', 'native'])
    assert result.exit_code == 0, result.output
    assert seen['shape_resolution'] == 1536
    assert CliRunner().invoke(app, args).exit_code != 0
    assert CliRunner().invoke(app, args[:-1] + ['1024', '--backend', 'native']).exit_code != 0
