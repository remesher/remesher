from typer.testing import CliRunner

from comfy_prompt_cli import app, native_backend


def test_cli_passes_no_decimation_to_native_generator(tmp_path, monkeypatch):
    image = tmp_path / 'input.png'
    image.write_bytes(b'input')
    seen = {}
    def generate(*args, **kwargs):
        seen.update(kwargs)
        return []
    monkeypatch.setattr(native_backend, 'generate', generate)
    result = CliRunner().invoke(app, ['image-to-glb', '--backend', 'native', '--image', str(image), '--no-decimation'])
    assert result.exit_code == 0, result.output
    assert seen['no_decimation'] is True


def test_cli_rejects_no_decimation_for_legacy(tmp_path):
    image = tmp_path / 'input.png'
    image.write_bytes(b'input')
    result = CliRunner().invoke(app, ['image-to-glb', '--image', str(image), '--no-decimation'])
    assert result.exit_code != 0
    assert 'requires a native backend' in result.output
