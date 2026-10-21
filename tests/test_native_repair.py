import pytest

from comfy_prompt_cli import native_backend


def test_fill_repair_precedes_uv_without_touching_sampling_or_capping():
    baseline = native_backend.build_prompt('x.png', no_decimation=True)
    graph = native_backend.build_prompt('x.png', no_decimation=True, mesh_repair='fill')
    assert graph['repair_fill'] == {'class_type': 'FillHoles', 'inputs': {
        'mesh': ['shape_decode', 0], 'max_perimeter': .03,
        'weld_epsilon_rel': 0., 'max_vertices': 16, 'fill_chains': False}}
    assert graph['unwrap']['inputs']['mesh'] == ['repair_fill', 0]
    for key in baseline.keys() - {'unwrap'}:
        assert graph[key] == baseline[key]
    assert all(n['class_type'] != 'DecimateMesh' for n in graph.values())


def test_solid_repair_explicit_portable_settings_and_no_precluster_cap():
    graph = native_backend.build_prompt('x.png', no_decimation=True,
        mesh_repair='solid', repair_resolution=1024, repair_max_perimeter=.02,
        repair_drop_small_components=.005)
    assert graph['repair_remesh'] == {'class_type': 'RemeshMesh', 'inputs': {
        'mesh': ['shape_decode', 0], 'resolution': 1024,
        'sign_mode': 'solid', 'sign_mode.fill': 20., 'sign_mode.qef': False,
        'band': 1., 'project_back': 0., 'fix_poles': False, 'smooth_iters': 0,
        'drop_small_components': .005, 'precluster_max_verts': 0}}
    assert graph['repair_fill']['inputs']['mesh'] == ['repair_remesh', 0]
    assert graph['repair_fill']['inputs']['max_perimeter'] == .02
    assert graph['unwrap']['inputs']['mesh'] == ['repair_fill', 0]
    assert graph['bake']['inputs']['reference_mesh'] == ['shape_decode', 0]


@pytest.mark.parametrize('options', [
    {'mesh_repair': 'invalid'}, {'mesh_repair': 'solid', 'no_decimation': False},
    {'repair_resolution': True}, {'repair_resolution': 0},
    {'repair_resolution': 2049}, {'repair_max_perimeter': float('nan')},
    {'repair_max_perimeter': -.01}, {'repair_max_perimeter': .031},
    {'repair_drop_small_components': .501}, {'repair_drop_small_components': True},
], ids=['mode','decimation','bool-resolution','zero-resolution','large-resolution',
        'nan-perimeter','negative-perimeter','large-perimeter','large-cleanup','bool-cleanup'])
def test_invalid_repair_settings_fail_closed(options):
    with pytest.raises(ValueError):
        native_backend.build_prompt('x.png', **{'no_decimation': True, **options})


def test_dynamic_combo_selected_children_are_validated():
    info = {'Node': {'output': [], 'input': {'required': {
        'mode': ['COMFY_DYNAMICCOMBO_V3', {'options': [
            {'key': 'solid', 'inputs': {'required': {
                'fill': ['FLOAT', {'min': 0, 'max': 1000}],
                'qef': ['BOOLEAN', {}]}}},
            {'key': 'udf', 'inputs': {'required': {'enclosed': ['BOOLEAN', {}]}}},
        ]}]}}}}
    inputs = {'mode': 'solid', 'mode.fill': 20., 'mode.qef': False}
    graph = {'n': {'class_type': 'Node', 'inputs': inputs}}
    native_backend.validate_prompt(graph, info)
    for bad in ({**inputs, 'mode.fill': -1}, {**inputs, 'mode.fill': float('nan')},
                {**inputs, 'mode.enclosed': True}, {'mode': 'solid'}):
        with pytest.raises(ValueError):
            native_backend.validate_prompt({'n': {'class_type': 'Node', 'inputs': bad}}, info)


def test_repair_exports_decoded_and_repaired_mesh_before_uv():
    graph = native_backend.build_prompt('x.png', no_decimation=True, mesh_repair='solid')
    assert graph['save_decoded']['inputs']['mesh'] == ['shape_decode', 0]
    assert graph['save_repaired']['inputs']['mesh'] == ['repair_fill', 0]
    assert graph['save_decoded']['class_type'] == 'SaveGLB'
    assert graph['save_repaired']['class_type'] == 'SaveGLB'
