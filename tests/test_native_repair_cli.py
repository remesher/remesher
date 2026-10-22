import pytest
from typer.testing import CliRunner

from comfy_prompt_cli import app, native_backend


def test_cli_repair_routes_native_options(tmp_path, monkeypatch):
    image = tmp_path / 'input.png'
    image.write_bytes(b'input')
    seen = {}
    def generate(*args, **kwargs):
        seen.update(kwargs)
        return []
    monkeypatch.setattr(native_backend, 'generate', generate)
    result = CliRunner().invoke(app, ['image-to-glb', '--backend', 'native',
        '--image', str(image), '--no-decimation', '--mesh-repair', 'solid',
        '--repair-resolution', '1024', '--repair-max-perimeter', '.02',
        '--repair-drop-small-components', '0'])
    assert result.exit_code == 0, result.output
    assert seen['mesh_repair'] == 'solid'
    assert seen['repair_resolution'] == 1024
    assert seen['repair_max_perimeter'] == .02
    assert seen['repair_drop_small_components'] == 0


@pytest.mark.parametrize('extra', [[], ['--backend', 'native'],
    ['--backend', 'native', '--no-decimation', '--mesh-repair', 'bad']])
def test_cli_rejects_legacy_capped_or_unknown_repair(tmp_path, extra):
    image = tmp_path / 'input.png'
    image.write_bytes(b'input')
    result = CliRunner().invoke(app, ['image-to-glb', '--image', str(image),
        '--mesh-repair', 'solid', *extra])
    assert result.exit_code != 0
    assert 'repair' in result.output.lower()
