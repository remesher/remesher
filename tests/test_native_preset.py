import pytest
from typer.testing import CliRunner
from comfy_prompt_cli import app, native_backend

QUALITY = 'quality-1536-solid768'


def test_plugin_and_cli_preset_contracts_match():
    import importlib.util
    from pathlib import Path
    from comfy_prompt_cli.native_presets import PRESETS, resolve_preset
    path = Path(__file__).resolve().parents[1] / 'integrations/hermes/__init__.py'
    spec = importlib.util.spec_from_file_location('preset_plugin', path)
    plugin = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plugin)
    assert plugin.NATIVE_PRESETS == PRESETS
    for name, values in PRESETS.items():
        assert plugin.resolve_native_preset(name, {}) == resolve_preset(name, {})
        for key, value in values.items():
            assert plugin.resolve_native_preset(name, {key: value}) == values
            for resolver in (resolve_preset, plugin.resolve_native_preset):
                with pytest.raises(ValueError, match='conflict'):
                    resolver(name, {key: None})


def test_configure_reports_resolved_preset_without_launch(tmp_path):
    import json
    from pathlib import Path
    import subprocess
    import sys
    config = tmp_path / 'config.json'
    config.write_text(json.dumps(dict(cli=sys.executable, backend='native', native_preset=QUALITY)))
    result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] /
        'integrations/hermes/scripts/configure.py'), '--input', str(config)],
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report['resolved_native_preset']['native_shape_resolution'] == 1536
    assert report['resolved_native_preset']['no_decimation'] is True
    assert report['gpu_generation_verified'] is False



@pytest.mark.parametrize('backend', ['native', 'native-local'])
def test_quality_cli_resolves_exact_values(tmp_path, monkeypatch, backend):
    from contextlib import nullcontext
    from comfy_prompt_cli import native_runtime
    monkeypatch.setattr(native_runtime, 'LocalRuntime', lambda *a, **k: nullcontext())
    image = tmp_path / 'x.png'
    image.write_bytes(b'input')
    seen = {}
    def generate(*args, **kwargs):
        seen.update(kwargs)
        return []
    monkeypatch.setattr(native_backend, 'generate', generate)
    result = CliRunner().invoke(app, ['image-to-glb', '--image', str(image),
        '--backend', backend, '--native-preset', QUALITY,
        '--native-python', '/python', '--native-checkout', '/checkout'])
    assert result.exit_code == 0, result.output
    assert {k: seen[k] for k in ('shape_resolution', 'atlas_resolution',
        'mesh_repair', 'repair_resolution', 'no_decimation')} == dict(
        shape_resolution=1536, atlas_resolution=4096, mesh_repair='solid',
        repair_resolution=768, no_decimation=True)
    graph = native_backend.build_prompt('x.png', **{k: v for k, v in seen.items()
        if k not in ('timeout', 'poll_interval', 'client_id')})
    assert 'decimate' not in graph
    assert graph['repair_remesh']['inputs']['precluster_max_verts'] == 0
    assert graph['save']['inputs']['mesh'] == ['smooth_normals', 0]


@pytest.mark.parametrize('flags', [
    ['--native-shape-resolution', '512'], ['--native-atlas-resolution', '1024'],
    ['--repair-resolution', '512'], ['--mesh-repair', 'none'],
    ['--target-face-num', '80000'], ['--repair-max-perimeter', '0'],
    ['--repair-drop-small-components', '0'],
])
def test_quality_rejects_conflicting_explicit_flags_before_network(tmp_path, flags):
    image = tmp_path / 'x.png'
    image.touch()
    result = CliRunner().invoke(app, ['image-to-glb', '--image', str(image),
        '--backend', 'native', '--native-preset', QUALITY, *flags])
    assert result.exit_code != 0
    assert 'conflict' in result.output.lower()


def test_preset_requires_native_backend(tmp_path):
    image = tmp_path / 'x.png'
    image.touch()
    result = CliRunner().invoke(app, ['image-to-glb', '--image', str(image),
        '--native-preset', QUALITY])
    assert result.exit_code != 0
    assert 'requires a native backend' in result.output
