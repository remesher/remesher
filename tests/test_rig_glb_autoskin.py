import inspect
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest
import typer
from typer.testing import CliRunner

import comfy_prompt_cli as cli
from comfy_prompt_cli import _postprocess_rig_downloads, app


def _write_hashed_summary(summary_path, output_path, **extra):
    payload = {
        "output_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        **extra,
    }
    summary_path.write_text(json.dumps(payload))


def test_default_auto_skin_worker_is_inside_installed_package():
    package_dir = Path(cli.__file__).resolve().parent
    expected = package_dir / "workers" / "blender_auto_skin_worker.py"

    assert cli.DEFAULT_AUTO_SKIN_WORKER == expected
    assert expected.is_file()


def test_rig_postprocess_preserves_raw_mia_and_replaces_expected_output(tmp_path, monkeypatch):
    downloaded = tmp_path / "robot_mia.glb"
    downloaded.write_bytes(b"raw-mia")
    worker = tmp_path / "blender_auto_skin_worker.py"
    worker.write_text("# worker")
    captured = {}

    def fake_run_bpy_worker(**kwargs):
        captured.update(kwargs)
        kwargs["positional_outputs"][0].write_bytes(b"auto-skinned")
        _write_hashed_summary(
            kwargs["summary_json"],
            kwargs["positional_outputs"][0],
            weighted_vertices=100,
        )

    monkeypatch.setattr(cli, "_run_bpy_worker", fake_run_bpy_worker)

    result = _postprocess_rig_downloads(
        [downloaded],
        auto_skin=True,
        worker_file=worker,
        bpy_container="comfy3d-test",
        weld_distance=1e-6,
        max_unweighted_fraction=0.001,
    )

    raw = tmp_path / "robot_mia.mia_raw.glb"
    summary = tmp_path / "robot_mia.autoskin.json"
    assert result == [downloaded]
    assert raw.read_bytes() == b"raw-mia"
    assert downloaded.read_bytes() == b"auto-skinned"
    assert summary.exists()
    assert captured["worker_file"] == worker
    assert captured["positional_inputs"] == [raw]
    candidate_output = captured["positional_outputs"][0]
    candidate_summary = captured["summary_json"]
    assert candidate_output.name == downloaded.name
    assert candidate_summary.name == summary.name
    assert candidate_output.parent == candidate_summary.parent
    assert candidate_output.parent.parent == tmp_path
    assert not candidate_output.parent.exists()
    assert captured["bpy_container"] == "comfy3d-test"
    assert captured["extra_args"] == [
        "--weld-distance",
        "1e-06",
        "--max-unweighted-fraction",
        "0.001",
    ]


def test_rig_postprocess_opt_out_leaves_mia_output_untouched(tmp_path, monkeypatch):
    downloaded = tmp_path / "robot_mia.glb"
    downloaded.write_bytes(b"raw-mia")

    def unexpected_worker(**kwargs):
        raise AssertionError("auto-skin worker must not run when disabled")

    monkeypatch.setattr(cli, "_run_bpy_worker", unexpected_worker)

    result = _postprocess_rig_downloads(
        [downloaded],
        auto_skin=False,
        worker_file=tmp_path / "missing.py",
        bpy_container="unused",
        weld_distance=1e-6,
        max_unweighted_fraction=0.001,
    )

    assert result == [downloaded]
    assert downloaded.read_bytes() == b"raw-mia"
    assert not (tmp_path / "robot_mia.mia_raw.glb").exists()


def test_rig_postprocess_rejects_preexisting_raw_destination(tmp_path, monkeypatch):
    downloaded = tmp_path / "robot_mia.glb"
    downloaded.write_bytes(b"current")
    raw = tmp_path / "robot_mia.mia_raw.glb"
    raw.write_bytes(b"older")
    worker = tmp_path / "worker.py"
    worker.write_text("# worker")
    called = False

    def unexpected_worker(**kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(cli, "_run_bpy_worker", unexpected_worker)

    with pytest.raises(typer.BadParameter, match="Refusing to overwrite"):
        _postprocess_rig_downloads(
            [downloaded],
            auto_skin=True,
            worker_file=worker,
            bpy_container="unused",
            weld_distance=1e-6,
            max_unweighted_fraction=0.001,
        )

    assert called is False
    assert downloaded.read_bytes() == b"current"
    assert raw.read_bytes() == b"older"


def test_rig_glb_help_defaults_to_auto_skin():
    result = CliRunner().invoke(app, ["rig-glb", "--help"])

    assert result.exit_code == 0
    assert "--auto-skin" in result.output
    assert "--no-auto-skin" in result.output
    option = inspect.signature(cli.rig_glb).parameters["auto_skin"].default
    assert option.default is True
    max_unweighted = inspect.signature(cli.rig_glb).parameters[
        "max_unweighted_fraction"
    ].default
    assert max_unweighted.default == 0.005


def test_text_to_rigged_glb_also_defaults_to_auto_skin():
    result = CliRunner().invoke(app, ["text-to-rigged-glb", "--help"])

    assert result.exit_code == 0
    assert "--auto-skin" in result.output
    assert "--no-auto-skin" in result.output
    option = inspect.signature(cli.text_to_rigged_glb).parameters["auto_skin"].default
    assert option.default is True
    max_unweighted = inspect.signature(cli.text_to_rigged_glb).parameters[
        "max_unweighted_fraction"
    ].default
    assert max_unweighted.default == 0.005


@pytest.mark.parametrize(
    ("extra_args", "expected_auto_skin"),
    [([], True), (["--no-auto-skin"], False)],
)
def test_rig_glb_command_dispatches_auto_skin_setting(
    tmp_path, monkeypatch, extra_args, expected_auto_skin
):
    config = tmp_path / "config.json"
    config.write_text('{"server_url": "http://example.invalid"}')
    workflow = tmp_path / "rig.json"
    workflow.write_text(
        '{"1":{"class_type":"Hy3DUploadMesh","inputs":{"mesh":"source.glb"}},'
        '"2":{"class_type":"MIAAutoRig","inputs":{}}}'
    )
    downloaded = tmp_path / "robot.glb"
    captured = {}

    monkeypatch.setattr(
        cli, "_submit_wait_and_download", lambda **kwargs: [downloaded]
    )

    def fake_postprocess(paths, **kwargs):
        captured.update(kwargs)
        return paths

    monkeypatch.setattr(cli, "_postprocess_rig_downloads", fake_postprocess)

    result = CliRunner().invoke(
        app,
        [
            "rig-glb",
            "--workflow-file",
            str(workflow),
            "--config",
            str(config),
            "--out-dir",
            str(tmp_path),
            *extra_args,
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["auto_skin"] is expected_auto_skin
    assert captured["worker_file"] == cli.DEFAULT_AUTO_SKIN_WORKER


@pytest.mark.parametrize(
    ("extra_args", "expected_auto_skin"),
    [([], True), (["--no-auto-skin"], False)],
)
def test_text_to_rigged_glb_command_dispatches_auto_skin_setting(
    tmp_path, monkeypatch, extra_args, expected_auto_skin
):
    image = tmp_path / "image.png"
    glb = tmp_path / "generated.glb"
    rigged = tmp_path / "rigged.glb"
    captured = {}

    monkeypatch.setattr(
        cli,
        "_load_config",
        lambda path: SimpleNamespace(server_url="http://example.invalid"),
    )

    def fake_submit_wait_and_download(**kwargs):
        if kwargs["extensions"] == cli.IMAGE_EXTENSIONS:
            return [image]
        return [rigged]

    monkeypatch.setattr(
        cli, "_submit_wait_and_download", fake_submit_wait_and_download
    )
    monkeypatch.setattr(cli, "_upload_input_image", lambda *args: "image.png")
    monkeypatch.setattr(cli, "_submit_prompt", lambda *args: {"prompt_id": "p"})

    def fake_asyncio_run(awaitable):
        awaitable.close()
        return {}, {}

    monkeypatch.setattr(cli.asyncio, "run", fake_asyncio_run)
    monkeypatch.setattr(cli, "_extract_file_refs", lambda *args: ["generated.glb"])
    monkeypatch.setattr(
        cli, "_download_from_history_by_ext", lambda *args: [glb]
    )
    monkeypatch.setattr(
        cli, "_upload_input_asset", lambda *args, **kwargs: "generated.glb"
    )

    def fake_postprocess(paths, **kwargs):
        captured.update(kwargs)
        return paths

    monkeypatch.setattr(cli, "_postprocess_rig_downloads", fake_postprocess)

    result = CliRunner().invoke(
        app,
        [
            "text-to-rigged-glb",
            "--prompt",
            "a robot",
            "--out-dir",
            str(tmp_path),
            *extra_args,
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["auto_skin"] is expected_auto_skin
    assert captured["worker_file"] == cli.DEFAULT_AUTO_SKIN_WORKER


def test_rig_postprocess_failure_preserves_raw_and_removes_partial_output(tmp_path, monkeypatch):
    downloaded = tmp_path / "robot_mia.glb"
    downloaded.write_bytes(b"raw-mia")
    worker = tmp_path / "worker.py"
    worker.write_text("# worker")

    def failed_worker(**kwargs):
        kwargs["positional_outputs"][0].write_bytes(b"partial")
        raise RuntimeError("weighting failed")

    monkeypatch.setattr(cli, "_run_bpy_worker", failed_worker)

    with pytest.raises(RuntimeError, match="weighting failed"):
        _postprocess_rig_downloads(
            [downloaded],
            auto_skin=True,
            worker_file=worker,
            bpy_container="unused",
            weld_distance=1e-6,
            max_unweighted_fraction=0.001,
        )

    assert not downloaded.exists()
    assert (tmp_path / "robot_mia.mia_raw.glb").read_bytes() == b"raw-mia"


def test_docker_worker_failure_copies_structured_summary_before_cleanup(
    tmp_path, monkeypatch
):
    worker = tmp_path / "worker.py"
    worker.write_text("# worker")
    input_glb = tmp_path / "input.glb"
    input_glb.write_bytes(b"glb")
    output_glb = tmp_path / "output.glb"
    summary = tmp_path / "output.autoskin.json"
    cleanup_calls = []

    monkeypatch.setattr(cli, "_python_has_bpy", lambda: False)
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda *args, **kwargs: type("Completed", (), {"returncode": 0})(),
    )

    def fake_worker_command(args, *, cwd=None):
        if "python" in args:
            raise typer.Exit(17)

    def fake_copy_from(container, source, dest):
        assert source.endswith("/output.autoskin.json")
        dest.write_text('{"error": "automatic heat failed"}')

    monkeypatch.setattr(cli, "_run_worker_command", fake_worker_command)
    monkeypatch.setattr(cli, "_copy_to_container", lambda *args: None)
    monkeypatch.setattr(cli, "_copy_from_container", fake_copy_from)

    original_run = cli.subprocess.run

    def track_cleanup(args, **kwargs):
        cleanup_calls.append(args)
        return original_run(args, **kwargs)

    monkeypatch.setattr(cli.subprocess, "run", track_cleanup)

    with pytest.raises(typer.Exit) as exc_info:
        cli._run_bpy_worker(
            worker_file=worker,
            positional_inputs=[input_glb],
            positional_outputs=[output_glb],
            extra_args=[],
            summary_json=summary,
            bpy_container="comfy3d-test",
        )

    assert exc_info.value.exit_code == 17
    assert summary.read_text() == '{"error": "automatic heat failed"}'
    assert any(call[-3:-1] == ["rm", "-rf"] for call in cleanup_calls)


@pytest.mark.parametrize("container", ["-evil", "bad:name", "bad/name", ""])
def test_docker_worker_rejects_invalid_container_names(
    tmp_path, monkeypatch, container
):
    worker = tmp_path / "worker.py"
    worker.write_text("# worker")
    input_glb = tmp_path / "input.glb"
    input_glb.write_bytes(b"glb")
    monkeypatch.setattr(cli, "_python_has_bpy", lambda: False)

    def unexpected_subprocess(*args, **kwargs):
        raise AssertionError("invalid container must be rejected before Docker")

    monkeypatch.setattr(cli.subprocess, "run", unexpected_subprocess)

    with pytest.raises(typer.BadParameter, match="Invalid Docker container name"):
        cli._run_bpy_worker(
            worker_file=worker,
            positional_inputs=[input_glb],
            positional_outputs=[tmp_path / "output.glb"],
            extra_args=[],
            summary_json=tmp_path / "summary.json",
            bpy_container=container,
        )


def test_docker_worker_distinguishes_missing_docker_executable(
    tmp_path, monkeypatch
):
    worker = tmp_path / "worker.py"
    worker.write_text("# worker")
    input_glb = tmp_path / "input.glb"
    input_glb.write_bytes(b"glb")
    monkeypatch.setattr(cli, "_python_has_bpy", lambda: False)
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            FileNotFoundError("docker")
        ),
    )

    with pytest.raises(typer.BadParameter, match="Docker executable.*not.*PATH"):
        cli._run_bpy_worker(
            worker_file=worker,
            positional_inputs=[input_glb],
            positional_outputs=[tmp_path / "output.glb"],
            extra_args=[],
            summary_json=tmp_path / "summary.json",
            bpy_container="comfy3d-test",
        )


def test_docker_worker_setup_copy_failure_still_cleans_remote_directory(
    tmp_path, monkeypatch
):
    worker = tmp_path / "worker.py"
    worker.write_text("# worker")
    input_glb = tmp_path / "input.glb"
    input_glb.write_bytes(b"glb")
    subprocess_calls = []

    monkeypatch.setattr(cli, "_python_has_bpy", lambda: False)

    def fake_subprocess_run(args, **kwargs):
        subprocess_calls.append(args)
        return SimpleNamespace(returncode=0)

    def fail_copy(*args, **kwargs):
        raise RuntimeError("copy failed")

    monkeypatch.setattr(cli.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(cli, "_run_worker_command", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_copy_to_container", fail_copy)

    with pytest.raises(RuntimeError, match="copy failed"):
        cli._run_bpy_worker(
            worker_file=worker,
            positional_inputs=[input_glb],
            positional_outputs=[tmp_path / "output.glb"],
            extra_args=[],
            summary_json=tmp_path / "summary.json",
            bpy_container="comfy3d-test",
        )

    assert any(
        call[:5] == ["docker", "exec", "--", "comfy3d-test", "rm"]
        and call[5] == "-rf"
        for call in subprocess_calls
    )


@pytest.mark.parametrize("distance", [math.nan, math.inf, -math.inf])
def test_rig_postprocess_rejects_nonfinite_weld_distance(
    tmp_path, monkeypatch, distance
):
    downloaded = tmp_path / "robot.glb"
    downloaded.write_bytes(b"raw")
    monkeypatch.setattr(
        cli,
        "_run_bpy_worker",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("worker must not run for invalid distance")
        ),
    )

    with pytest.raises(typer.BadParameter, match="finite and greater than 0"):
        _postprocess_rig_downloads(
            [downloaded],
            auto_skin=True,
            worker_file=cli.DEFAULT_AUTO_SKIN_WORKER,
            bpy_container="unused",
            weld_distance=distance,
            max_unweighted_fraction=0.005,
        )


def test_move_file_noreplace_preserves_concurrent_destination(tmp_path):
    source = tmp_path / "download.glb"
    destination = tmp_path / "download.mia_raw.glb"
    source.write_bytes(b"new")
    destination.write_bytes(b"concurrent")

    with pytest.raises(FileExistsError):
        cli._move_file_noreplace(source, destination)

    assert source.read_bytes() == b"new"
    assert destination.read_bytes() == b"concurrent"


def test_cli_reports_enotsup_when_libc_lacks_renameat2(
    tmp_path, monkeypatch
):
    source = tmp_path / "source.glb"
    destination = tmp_path / "destination.glb"
    source.write_bytes(b"source")
    monkeypatch.setattr(cli.sys, "platform", "linux")
    monkeypatch.setattr(
        cli.ctypes,
        "CDLL",
        lambda *args, **kwargs: SimpleNamespace(),
    )

    with pytest.raises(OSError, match="does not expose renameat2") as exc_info:
        cli._move_file_noreplace(source, destination)

    assert exc_info.value.errno == cli.errno.ENOTSUP
    assert source.read_bytes() == b"source"
    assert not destination.exists()


def test_postprocess_never_replaces_concurrently_created_final_glb(
    tmp_path, monkeypatch
):
    downloaded = tmp_path / "robot.glb"
    downloaded.write_bytes(b"raw")
    def racing_worker(**kwargs):
        downloaded.write_bytes(b"concurrent-final")
        kwargs["positional_outputs"][0].write_bytes(b"worker-final")
        _write_hashed_summary(
            kwargs["summary_json"], kwargs["positional_outputs"][0], ok=True
        )

    monkeypatch.setattr(cli, "_run_bpy_worker", racing_worker)

    with pytest.raises(typer.BadParameter, match="concurrently created"):
        _postprocess_rig_downloads(
            [downloaded],
            auto_skin=True,
            worker_file=cli.DEFAULT_AUTO_SKIN_WORKER,
            bpy_container="unused",
            weld_distance=1e-6,
            max_unweighted_fraction=0.005,
        )

    assert downloaded.read_bytes() == b"concurrent-final"
    assert not (tmp_path / "robot.autoskin.json").exists()


def test_postprocess_never_replaces_concurrently_created_summary(
    tmp_path, monkeypatch
):
    downloaded = tmp_path / "robot.glb"
    downloaded.write_bytes(b"raw")
    public_summary = tmp_path / "robot.autoskin.json"

    def racing_worker(**kwargs):
        public_summary.write_text('{"owner": "concurrent"}')
        kwargs["positional_outputs"][0].write_bytes(b"worker-final")
        _write_hashed_summary(
            kwargs["summary_json"],
            kwargs["positional_outputs"][0],
            owner="worker",
        )

    monkeypatch.setattr(cli, "_run_bpy_worker", racing_worker)

    with pytest.raises(typer.BadParameter, match="concurrently created"):
        _postprocess_rig_downloads(
            [downloaded],
            auto_skin=True,
            worker_file=cli.DEFAULT_AUTO_SKIN_WORKER,
            bpy_container="unused",
            weld_distance=1e-6,
            max_unweighted_fraction=0.005,
        )

    assert public_summary.read_text() == '{"owner": "concurrent"}'
    assert downloaded.read_bytes() == b"worker-final"


def test_pair_rejects_mismatched_hash_before_publication(tmp_path):
    candidate_output = tmp_path / "candidate.glb"
    candidate_summary = tmp_path / "candidate.json"
    output_glb = tmp_path / "final.glb"
    summary_json = tmp_path / "final.json"
    candidate_output.write_bytes(b"candidate")
    candidate_summary.write_text(
        json.dumps({"output_sha256": "0" * 64, "owner": "worker"})
    )

    with pytest.raises(typer.BadParameter, match="hash does not match"):
        cli._publish_file_pair_noreplace(
            candidate_output=candidate_output,
            output_glb=output_glb,
            candidate_summary=candidate_summary,
            summary_json=summary_json,
        )

    assert not summary_json.exists()
    assert not output_glb.exists()


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"{truncated", "not valid JSON"),
        (b"\xff", "not valid JSON"),
        (b"[]", "must be a JSON object"),
    ],
)
def test_pair_rejects_malformed_summary_before_publication(
    tmp_path, payload, message
):
    candidate_output = tmp_path / "candidate.glb"
    candidate_summary = tmp_path / "candidate.json"
    output_glb = tmp_path / "final.glb"
    summary_json = tmp_path / "final.json"
    candidate_output.write_bytes(b"candidate")
    candidate_summary.write_bytes(payload)

    with pytest.raises(typer.BadParameter, match=rf"{message}.*candidate.json"):
        cli._publish_file_pair_noreplace(
            candidate_output=candidate_output,
            output_glb=output_glb,
            candidate_summary=candidate_summary,
            summary_json=summary_json,
        )

    assert not summary_json.exists()
    assert not output_glb.exists()


def test_postprocess_validation_errors_use_cli_flag_names(tmp_path):
    downloaded = tmp_path / "robot.glb"
    downloaded.write_bytes(b"raw")

    with pytest.raises(typer.BadParameter, match="--auto-skin-weld-distance"):
        _postprocess_rig_downloads(
            [downloaded],
            auto_skin=True,
            worker_file=cli.DEFAULT_AUTO_SKIN_WORKER,
            bpy_container="unused",
            weld_distance=float("inf"),
            max_unweighted_fraction=0.005,
        )
    with pytest.raises(typer.BadParameter, match="--max-unweighted-fraction"):
        _postprocess_rig_downloads(
            [downloaded],
            auto_skin=True,
            worker_file=cli.DEFAULT_AUTO_SKIN_WORKER,
            bpy_container="unused",
            weld_distance=1e-6,
            max_unweighted_fraction=2.0,
        )
