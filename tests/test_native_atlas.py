import copy
import pytest
from comfy_prompt_cli.native_backend import build_prompt


def test_atlas_changes_only_unwrap_and_bake():
    options = dict(model='pixal3d', shape_resolution=1536, camera_angle=42.75103780924466,
                   no_decimation=True, mesh_repair='solid', repair_resolution=768)
    baseline = build_prompt('padded.png', **options)
    expected = copy.deepcopy(baseline)
    expected['unwrap']['inputs']['resolution'] = 4096
    expected['bake']['inputs']['texture_size'] = 4096
    assert build_prompt('padded.png', atlas_resolution=4096, **options) == expected
    assert build_prompt('padded.png', atlas_resolution=1024, **options) == baseline


@pytest.mark.parametrize('value', [True, 0, 2048, 4096.0, '4096', None])
def test_invalid_atlas(value):
    with pytest.raises(ValueError, match='atlas resolution'):
        build_prompt('x.png', atlas_resolution=value)


def test_cli_atlas_routes_and_legacy_rejects(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from comfy_prompt_cli import app, native_backend
    image = tmp_path / 'x.png'
    image.write_bytes(b'input')
    seen = {}
    def generate(*args, **kwargs):
        seen.update(kwargs)
        return []
    monkeypatch.setattr(native_backend, 'generate', generate)
    args = ['image-to-glb', '--image', str(image), '--native-atlas-resolution', '4096']
    result = CliRunner().invoke(app, args + ['--backend', 'native'])
    assert result.exit_code == 0, result.output
    assert seen['atlas_resolution'] == 4096
    assert CliRunner().invoke(app, args).exit_code != 0
    assert CliRunner().invoke(app, args[:-1] + ['2048', '--backend', 'native']).exit_code != 0
