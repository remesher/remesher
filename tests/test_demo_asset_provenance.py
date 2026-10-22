"""Demo retargeting must work without redistributing a third-party FBX."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS = sorted((ROOT / 'notebooks').glob('0[123]_*.ipynb'))


def test_third_party_template_is_not_bundled():
    assert not (ROOT / 'workspace/input/animation_templates/mixamo/Mma_Kick.fbx').exists()
    assert (ROOT / 'workspace/input/demo/pencil_sketch_character.jpg').is_file()


@pytest.mark.parametrize('notebook', NOTEBOOKS, ids=lambda p: p.name)
def test_optional_retarget_cell_without_fbx(notebook, tmp_path, monkeypatch):
    def unexpected_process(*args, **kwargs):
        pytest.fail('No FBX supplied: must not retarget or download an animation')

    monkeypatch.setattr('subprocess.run', unexpected_process)
    cells = json.loads(notebook.read_text())['cells']
    source = next(''.join(c['source']) for c in cells
                  if c['cell_type'] == 'code' and "'retarget-glb'" in ''.join(c['source']))
    rigged = tmp_path / 'rigged.glb'
    rigged.touch()
    namespace = dict(GENERATED_RIGGED_GLB_PATH=rigged, USER_FBX_PATH=None,
                     OUTPUT=tmp_path, INPUT=tmp_path, ROOT=ROOT, WORKSPACE=tmp_path)
    exec(compile(source, str(notebook), 'exec'), namespace)
    output_key = 'ANIMATED_GLB_PATH' if notebook.name.startswith('03') else 'KICK_ANIMATED_GLB_PATH'
    assert namespace[output_key] == rigged


@pytest.mark.parametrize('notebook', NOTEBOOKS, ids=lambda p: p.name)
def test_explicit_missing_fbx_fails_without_downloading(notebook, tmp_path, monkeypatch):
    def unexpected_process(*args, **kwargs):
        pytest.fail('Missing local FBX must fail before invoking a subprocess')

    monkeypatch.setattr('subprocess.run', unexpected_process)
    cells = json.loads(notebook.read_text())['cells']
    source = next(''.join(c['source']) for c in cells
                  if c['cell_type'] == 'code' and "'retarget-glb'" in ''.join(c['source']))
    rigged = tmp_path / 'rigged.glb'
    rigged.touch()
    missing = tmp_path / 'missing.fbx'
    namespace = dict(GENERATED_RIGGED_GLB_PATH=rigged, USER_FBX_PATH=missing,
                     KICK_ANIMATION_FBX_OVERRIDE=missing, OUTPUT=tmp_path,
                     INPUT=tmp_path, ROOT=ROOT, WORKSPACE=tmp_path)
    with pytest.raises(FileNotFoundError):
        exec(compile(source, '<retarget-cell>', 'exec'), namespace)


def test_upload_without_fbx_clears_previous_animation(tmp_path):
    import ast
    from types import SimpleNamespace

    notebook = next(p for p in NOTEBOOKS if p.name.startswith('03'))
    cells = json.loads(notebook.read_text())['cells']
    source = next(''.join(c['source']) for c in cells if 'def save_uploads' in ''.join(c['source']))
    functions = ast.Module(body=[n for n in ast.parse(source).body
                               if isinstance(n, ast.FunctionDef)], type_ignores=[])
    class Status:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def clear_output(self):
            pass

    namespace = dict(UPLOAD_DIR=tmp_path, status=Status(),
                     image_upload=SimpleNamespace(value={'sketch.jpg': {'content': b'test image'}}),
                     fbx_upload=SimpleNamespace(value={}), USER_FBX_PATH=tmp_path / 'old.fbx')
    exec(compile(functions, '<upload-functions>', 'exec'), namespace)
    namespace['save_uploads']()
    assert namespace['USER_FBX_PATH'] is None
    assert namespace['USER_IMAGE_PATH'].read_bytes() == b'test image'


def test_notebooks_do_not_reference_removed_template():
    for notebook in NOTEBOOKS:
        assert 'Mma_Kick' not in notebook.read_text()
