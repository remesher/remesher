import inspect
import math
from types import SimpleNamespace

import pytest

from comfy_prompt_cli.workers import blender_auto_skin_worker as worker
from comfy_prompt_cli.workers.blender_auto_skin_worker import (
    _count_positive_deform_weights,
    _matrix_max_abs_delta,
    _new_temp_glb_path,
    _promote_file_noreplace,
    _removed_component_count,
    _remove_temp_glb_path,
    _small_component_vertices_to_remove,
    _validate_weld_distance,
    _write_json_noreplace,
)


def _group_ref(index, weight):
    return SimpleNamespace(group=index, weight=weight)


def test_positive_deform_weight_count_rejects_zero_and_nondeform_groups():
    mesh = SimpleNamespace(
        vertex_groups=[
            SimpleNamespace(index=0, name="DeformBone"),
            SimpleNamespace(index=1, name="ControlBone"),
        ],
        data=SimpleNamespace(
            vertices=[
                SimpleNamespace(groups=[_group_ref(0, 0.0)]),
                SimpleNamespace(groups=[_group_ref(1, 1.0)]),
                SimpleNamespace(groups=[_group_ref(0, 0.25)]),
                SimpleNamespace(groups=[]),
            ]
        ),
    )
    armature = SimpleNamespace(
        data=SimpleNamespace(
            bones=[
                SimpleNamespace(name="DeformBone", use_deform=True),
                SimpleNamespace(name="ControlBone", use_deform=False),
            ]
        )
    )

    assert _count_positive_deform_weights(mesh, armature) == 1


def test_temp_glb_paths_are_unique_and_do_not_touch_deterministic_neighbor(tmp_path):
    output = tmp_path / "robot.glb"
    deterministic_neighbor = tmp_path / ".robot.normalized.glb"
    deterministic_neighbor.write_bytes(b"user-data")

    first = _new_temp_glb_path(output, "normalized")
    second = _new_temp_glb_path(output, "normalized")

    assert first != second
    assert first.parent.parent == tmp_path
    assert second.parent.parent == tmp_path
    assert first.parent.stat().st_mode & 0o777 == 0o700
    assert second.parent.stat().st_mode & 0o777 == 0o700
    assert not first.exists()
    assert not second.exists()
    assert deterministic_neighbor.read_bytes() == b"user-data"

    _remove_temp_glb_path(first)
    _remove_temp_glb_path(second)
    assert not first.parent.exists()
    assert not second.parent.exists()


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, 0.0, -1.0])
def test_weld_distance_must_be_finite_and_positive(value):
    with pytest.raises(ValueError, match="finite and greater than 0"):
        _validate_weld_distance(value)


def test_world_matrix_delta_and_parenting_contract_are_explicit():
    identity = (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )
    translated = tuple(
        tuple(value + (0.25 if row == 0 and column == 3 else 0.0)
              for column, value in enumerate(values))
        for row, values in enumerate(identity)
    )

    assert _matrix_max_abs_delta(identity, identity) == 0.0
    assert _matrix_max_abs_delta(identity, translated) == 0.25
    source = "".join(inspect.getsource(worker.auto_skin_glb).split())
    assert 'parent_set(type="ARMATURE_AUTO",keep_transform=True)' in source


def test_final_promotion_never_replaces_concurrent_destination(tmp_path):
    candidate = tmp_path / "candidate.glb"
    destination = tmp_path / "final.glb"
    candidate.write_bytes(b"candidate")
    destination.write_bytes(b"concurrent")

    with pytest.raises(FileExistsError):
        _promote_file_noreplace(candidate, destination)

    assert candidate.read_bytes() == b"candidate"
    assert destination.read_bytes() == b"concurrent"


def test_summary_write_never_replaces_concurrent_destination(tmp_path):
    summary = tmp_path / "result.json"
    summary.write_text('{"owner": "concurrent"}')

    with pytest.raises(FileExistsError):
        _write_json_noreplace(summary, {"owner": "worker"})

    assert summary.read_text() == '{"owner": "concurrent"}'


def test_worker_reports_enotsup_when_libc_lacks_renameat2(
    tmp_path, monkeypatch
):
    source = tmp_path / "source.glb"
    destination = tmp_path / "destination.glb"
    source.write_bytes(b"source")
    monkeypatch.setattr(worker.sys, "platform", "linux")
    monkeypatch.setattr(
        worker.ctypes,
        "CDLL",
        lambda *args, **kwargs: SimpleNamespace(),
    )

    with pytest.raises(OSError, match="does not expose renameat2") as exc_info:
        _promote_file_noreplace(source, destination)

    assert exc_info.value.errno == worker.errno.ENOTSUP
    assert source.read_bytes() == b"source"
    assert not destination.exists()


def test_small_component_cleanup_never_selects_the_sole_or_largest_component():
    sole = {0: [0, 1, 2]}
    multiple = {0: [0, 1, 2], 3: [3], 4: [4, 5]}
    sole_removed = _small_component_vertices_to_remove(sole, 128)
    multiple_removed = _small_component_vertices_to_remove(multiple, 128)

    assert sole_removed == []
    assert _removed_component_count(sole, sole_removed) == 0
    assert multiple_removed == [3, 4, 5]
    assert _removed_component_count(multiple, multiple_removed) == 2


def test_failure_still_emits_diagnostics_when_summary_already_exists(
    tmp_path, monkeypatch, capsys
):
    summary = tmp_path / "summary.json"
    summary.write_text('{"owner": "peer"}')
    monkeypatch.setattr(
        worker.sys,
        "argv",
        ["worker", "input.glb", "output.glb", "--summary-json", str(summary)],
    )

    def fail_skin(*args, **kwargs):
        raise RuntimeError("original weighting failure")

    monkeypatch.setattr(worker, "auto_skin_glb", fail_skin)

    assert worker.main() == 1
    captured = capsys.readouterr()
    assert "original weighting failure" in captured.err
    assert "summary_write_error" in captured.err
    assert summary.read_text() == '{"owner": "peer"}'


def test_success_reports_controlled_error_when_summary_already_exists(
    tmp_path, monkeypatch, capsys
):
    summary = tmp_path / "summary.json"
    summary.write_text('{"owner": "peer"}')
    monkeypatch.setattr(
        worker.sys,
        "argv",
        ["worker", "input.glb", "output.glb", "--summary-json", str(summary)],
    )
    monkeypatch.setattr(
        worker,
        "auto_skin_glb",
        lambda *args, **kwargs: {"weighted_vertices": 10},
    )

    assert worker.main() == 1
    captured = capsys.readouterr()
    assert "summary_write_error" in captured.err
    assert '"worker_result"' in captured.err
    assert summary.read_text() == '{"owner": "peer"}'
