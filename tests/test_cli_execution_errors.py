import json

import pytest
import typer
from typer.testing import CliRunner

import comfy_prompt_cli as cli
from comfy_prompt_cli import (
    _raise_for_history_error,
    _require_downloaded_artifacts,
    _submit_wait_and_download,
)


def test_execution_error_history_is_rejected():
    history_item = {
        "outputs": {},
        "status": {
            "status_str": "error",
            "completed": False,
            "messages": [
                [
                    "execution_error",
                    {
                        "node_id": "42",
                        "node_type": "MIAAutoRig",
                        "exception_type": "AttributeError",
                        "exception_message": "'NoneType' object has no attribute 'shape'",
                    },
                ]
            ],
        },
    }

    with pytest.raises(typer.BadParameter) as exc_info:
        _raise_for_history_error("prompt-123", history_item)

    message = str(exc_info.value)
    assert "prompt-123" in message
    assert "MIAAutoRig" in message
    assert "'NoneType' object has no attribute 'shape'" in message


def test_incomplete_history_is_rejected_even_without_error_message():
    history_item = {
        "outputs": {},
        "status": {"completed": False, "messages": []},
    }

    with pytest.raises(typer.BadParameter) as exc_info:
        _raise_for_history_error("prompt-incomplete", history_item)

    assert "prompt-incomplete" in str(exc_info.value)


def test_missing_required_artifact_is_rejected():
    with pytest.raises(typer.BadParameter) as exc_info:
        _require_downloaded_artifacts(
            prompt_id="prompt-456",
            downloaded=[],
            extensions={".glb"},
        )

    message = str(exc_info.value)
    assert "prompt-456" in message
    assert ".glb" in message


def test_wait_command_rejects_missing_requested_glb(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"server_url": "http://127.0.0.1:8188/"}))

    async def fake_wait_for_completion(*args, **kwargs):
        return {"queue_running": [], "queue_pending": []}, {"outputs": {}}

    monkeypatch.setattr(cli, "_wait_for_completion", fake_wait_for_completion)
    monkeypatch.setattr(cli, "_download_from_history", lambda *args, **kwargs: [])

    result = CliRunner().invoke(
        cli.app,
        ["wait", "prompt-789", "--config", str(config)],
    )

    assert result.exit_code != 0
    assert "prompt-789" in result.output
    assert ".glb" in result.output
    assert "--no-download-glb" in result.output


def test_missing_artifact_is_not_reported_as_completed(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "_submit_prompt",
        lambda *args, **kwargs: {"prompt_id": "prompt-missing"},
    )

    async def fake_wait_for_completion(*args, **kwargs):
        return {"queue_running": [], "queue_pending": []}, {"outputs": {}}

    monkeypatch.setattr(cli, "_wait_for_completion", fake_wait_for_completion)
    monkeypatch.setattr(
        cli,
        "_download_from_history_by_ext",
        lambda *args, **kwargs: [],
    )

    with pytest.raises(typer.BadParameter):
        _submit_wait_and_download(
            base="http://127.0.0.1:8188",
            prompt={},
            client_id=None,
            poll_interval=0.5,
            timeout=1.0,
            out_dir=tmp_path,
            extensions={".glb"},
        )

    assert "Prompt completed." not in capsys.readouterr().out
