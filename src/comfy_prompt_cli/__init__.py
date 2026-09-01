from __future__ import annotations

import asyncio
import ctypes
import errno
import hashlib
import importlib
import json
import math
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
import typer
from pydantic import BaseModel, HttpUrl, ValidationError

from .image_padding import pad_image_on_canvas

app = typer.Typer(help="Send prompts to a ComfyUI server.")
CONFIG_PATH = Path("config.json")
DEFAULT_TEXT_TO_IMAGE_WORKFLOW = Path("examples/qwen_image_2512.json")
DEFAULT_IMAGE_TEXT_TO_IMAGE_WORKFLOW = Path("examples/qwen_image_edit_2511.json")
DEFAULT_IMAGE_TO_GLB_WORKFLOW = Path("examples/img_to_trellis2.json")
DEFAULT_RIG_GLB_WORKFLOW = Path("examples/rig_glb_mia.json")
DEFAULT_AUTO_SKIN_WORKER = (
    Path(__file__).resolve().parent / "workers" / "blender_auto_skin_worker.py"
)
DEFAULT_RETARGET_WORKER = Path("docker/demo-jupyter/scripts/arp_retarget_worker.py")
DEFAULT_SKIN_CLEANUP_WORKER = Path("docker/demo-jupyter/scripts/anatomical_cleanup_worker.py")
DEFAULT_USDZ_WORKER = Path("docker/demo-jupyter/scripts/glb_to_usdz_worker.py")
DEFAULT_POSE_GLB_WORKER = Path("docker/demo-jupyter/scripts/pose_glb_worker.py")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
GLB_EXTENSIONS = {".glb"}
USDZ_EXTENSIONS = {".usdz"}


class AppConfig(BaseModel):
    server_url: HttpUrl


def _load_config(path: Path = CONFIG_PATH) -> AppConfig:
    if not path.exists():
        raise typer.BadParameter(
            f"Config file not found at {path}. Run: comfy-prompt-cli config init"
        )

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return AppConfig.model_validate(raw)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"Invalid JSON in {path}: {exc}") from exc
    except ValidationError as exc:
        raise typer.BadParameter(f"Invalid config in {path}: {exc}") from exc


def _extract_prompt_payload(data: dict[str, Any]) -> dict[str, Any]:
    # Accept either {"prompt": {...}} wrapper or direct prompt mapping.
    if "prompt" in data and isinstance(data["prompt"], dict):
        return data["prompt"]

    # Heuristic: UI workflow export (graph format) is not directly valid for /prompt.
    if "nodes" in data and "links" in data:
        raise typer.BadParameter(
            "This looks like a ComfyUI workflow export (nodes/links graph). "
            "The /prompt route expects API prompt JSON. In ComfyUI, export/copy "
            "the API prompt format, or provide a file with a top-level 'prompt' object."
        )

    if isinstance(data, dict):
        return data

    raise typer.BadParameter("Prompt JSON must be an object.")


def _load_prompt_from_file(prompt_file: Path) -> dict[str, Any]:
    if not prompt_file.exists():
        raise typer.BadParameter(f"Prompt file not found: {prompt_file}")

    try:
        data = json.loads(prompt_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"Invalid JSON in {prompt_file}: {exc}") from exc

    if not isinstance(data, dict):
        raise typer.BadParameter("Prompt JSON root must be an object.")

    return _extract_prompt_payload(data)


def _find_node_by_class(
    prompt: dict[str, Any], class_type: str
) -> tuple[str, dict[str, Any]] | None:
    for node_id, node in prompt.items():
        if isinstance(node, dict) and node.get("class_type") == class_type:
            return node_id, node
    return None


def _set_input_if_node(node: dict[str, Any], key: str, value: Any) -> bool:
    inputs = node.get("inputs")
    if isinstance(inputs, dict):
        inputs[key] = value
        return True
    return False


def _set_input_on_first_node_by_class(
    prompt: dict[str, Any], class_type: str, key: str, value: Any
) -> str | None:
    found = _find_node_by_class(prompt, class_type)
    if not found:
        return None
    if not _set_input_if_node(found[1], key, value):
        return None
    return found[0]


def _replace_all_load_image_inputs(
    prompt: dict[str, Any], image_name: str
) -> list[str]:
    updated_nodes: list[str] = []
    for node_id, node in prompt.items():
        if not isinstance(node, dict) or node.get("class_type") != "LoadImage":
            continue
        if _set_input_if_node(node, "image", image_name):
            updated_nodes.append(str(node_id))
    return updated_nodes


def _apply_overrides(
    prompt: dict[str, Any],
    positive_prompt: str | None,
    mesh_seed: int | None,
    target_face_num: int | None,
    filename_prefix: str | None,
    texture_seed: int | None,
) -> list[str]:
    changes: list[str] = []

    if positive_prompt is not None:
        updated = 0
        for node_id, node in prompt.items():
            if not isinstance(node, dict):
                continue

            class_type = node.get("class_type")
            if class_type not in {"CLIPTextEncode", "TextEncodeQwenImageEditPlus"}:
                continue

            meta = node.get("_meta", {}) if isinstance(node.get("_meta"), dict) else {}
            title = str(meta.get("title", "")).lower()
            inputs = (
                node.get("inputs", {}) if isinstance(node.get("inputs"), dict) else {}
            )

            if "negative" in title:
                continue

            if class_type == "CLIPTextEncode":
                if "text" not in inputs:
                    continue
                if "positive" in title or str(inputs.get("text", "")).strip():
                    inputs["text"] = positive_prompt
                    updated += 1
                    changes.append(f"prompt -> node {node_id}")
                continue

            if "prompt" not in inputs:
                continue
            if "positive" in title or str(inputs.get("prompt", "")).strip():
                inputs["prompt"] = positive_prompt
                updated += 1
                changes.append(f"prompt -> node {node_id}")
        if updated == 0:
            raise typer.BadParameter(
                "Could not find a positive prompt encoding node to override prompt text."
            )

    if mesh_seed is not None:
        found = _find_node_by_class(prompt, "Trellis2MeshWithVoxelAdvancedGenerator")
        if not found or not _set_input_if_node(found[1], "seed", mesh_seed):
            raise typer.BadParameter(
                "Could not find Trellis2MeshWithVoxelAdvancedGenerator for mesh_seed override."
            )
        changes.append(f"mesh_seed={mesh_seed} -> node {found[0]}")

    if target_face_num is not None:
        found = _find_node_by_class(prompt, "Trellis2SimplifyMesh")
        if not found or not _set_input_if_node(
            found[1], "target_face_num", target_face_num
        ):
            raise typer.BadParameter(
                "Could not find Trellis2SimplifyMesh for target_face_num override."
            )
        changes.append(f"target_face_num={target_face_num} -> node {found[0]}")

    if filename_prefix is not None:
        found = _find_node_by_class(prompt, "Trellis2ExportMesh")
        if not found:
            found = _find_node_by_class(prompt, "Hy3DExportMesh")
        if not found or not _set_input_if_node(
            found[1], "filename_prefix", filename_prefix
        ):
            raise typer.BadParameter(
                "Could not find Trellis2ExportMesh or Hy3DExportMesh for filename_prefix override."
            )
        changes.append(f"filename_prefix={filename_prefix} -> node {found[0]}")

    if texture_seed is not None:
        found = _find_node_by_class(prompt, "Trellis2MeshTexturing")
        if not found or not _set_input_if_node(found[1], "seed", texture_seed):
            raise typer.BadParameter(
                "Could not find Trellis2MeshTexturing for texture_seed override."
            )
        changes.append(f"texture_seed={texture_seed} -> node {found[0]}")

    return changes


def _submit_prompt(
    base: str, prompt: dict[str, Any], client_id: str | None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "prompt": prompt,
        "client_id": client_id or str(uuid.uuid4()),
    }
    with httpx.Client(timeout=60.0) as client:
        r = client.post(f"{base}/prompt", json=payload)
        r.raise_for_status()
        return r.json()


def _build_ws_url(base: str, client_id: str) -> str:
    ws_base = base
    if base.startswith("https://"):
        ws_base = "wss://" + base[len("https://") :]
    elif base.startswith("http://"):
        ws_base = "ws://" + base[len("http://") :]
    return f"{ws_base}/ws?{urlencode({'clientId': client_id})}"


def _format_ws_progress_line(message: dict[str, Any], prompt_id: str) -> str | None:
    msg_type = message.get("type")
    data = message.get("data")
    if not isinstance(msg_type, str):
        return None

    payload = data if isinstance(data, dict) else {}
    payload_prompt_id = payload.get("prompt_id")
    if isinstance(payload_prompt_id, str) and payload_prompt_id != prompt_id:
        return None

    if msg_type == "execution_start":
        return f"WS: execution started for prompt_id={prompt_id}"

    if msg_type == "executing":
        node = payload.get("node")
        if node is None:
            return f"WS: execution finished for prompt_id={prompt_id}"
        return f"WS: executing node {node}"

    if msg_type == "executed":
        node = payload.get("node")
        if node is None:
            return None
        return f"WS: completed node {node}"

    if msg_type == "progress":
        value = payload.get("value")
        max_value = payload.get("max")
        if isinstance(value, int) and isinstance(max_value, int) and max_value > 0:
            percent = int((value / max_value) * 100)
            return f"WS: progress {value}/{max_value} ({percent}%)"
        return None

    if msg_type == "execution_cached":
        nodes = payload.get("nodes")
        if isinstance(nodes, list):
            return f"WS: using cached outputs for nodes {', '.join(map(str, nodes))}"
        return "WS: using cached outputs"

    if msg_type == "execution_error":
        error_message = payload.get("exception_message")
        if isinstance(error_message, str) and error_message.strip():
            return f"WS: execution error: {error_message}"
        return "WS: execution error"

    if msg_type == "status":
        status = payload.get("status")
        if not isinstance(status, dict):
            return None
        exec_info = status.get("exec_info")
        if not isinstance(exec_info, dict):
            return None
        queue_remaining = exec_info.get("queue_remaining")
        if isinstance(queue_remaining, int):
            return f"WS: queue remaining={queue_remaining}"

    return None


async def _stream_ws_progress(
    base: str,
    client_id: str,
    prompt_id: str,
    stop_event: asyncio.Event,
) -> None:
    try:
        websockets = importlib.import_module("websockets")
    except Exception:
        typer.echo("WS: websockets package not available; continuing with polling.")
        return

    ws_url = _build_ws_url(base, client_id)
    try:
        async with websockets.connect(ws_url, open_timeout=10, ping_interval=20) as ws:
            typer.echo(f"WS: connected ({ws_url})")
            last_line: str | None = None

            while not stop_event.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    return

                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="ignore")

                if not isinstance(raw, str):
                    continue

                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                if not isinstance(message, dict):
                    continue

                line = _format_ws_progress_line(message, prompt_id)
                if line and line != last_line:
                    typer.echo(line)
                    last_line = line
    except Exception:
        typer.echo("WS: unavailable; continuing with polling.")


def _upload_input_image(base: str, image_path: Path, overwrite: bool = True) -> str:
    return _upload_input_asset(base, image_path, overwrite=overwrite, label="Image")


def _upload_input_asset(
    base: str, file_path: Path, overwrite: bool = True, label: str = "File"
) -> str:
    if not file_path.exists():
        raise typer.BadParameter(f"{label} file not found: {file_path}")

    guessed_type, _ = mimetypes.guess_type(str(file_path))
    content_type = guessed_type or "application/octet-stream"
    with file_path.open("rb") as f, httpx.Client(timeout=120.0) as client:
        files = {"image": (file_path.name, f, content_type)}
        data = {"overwrite": "true" if overwrite else "false", "type": "input"}
        resp = client.post(f"{base}/upload/image", files=files, data=data)
        resp.raise_for_status()
        payload = resp.json()

    if isinstance(payload, dict):
        name = payload.get("name")
        if isinstance(name, str) and name.strip():
            subfolder = payload.get("subfolder")
            if isinstance(subfolder, str) and subfolder.strip():
                return f"{subfolder}/{name}"
            return name

    raise typer.BadParameter(
        f"Unexpected {label.lower()} upload response: {json.dumps(payload)}"
    )


@app.command("health")
def health(
    config: Path = typer.Option(CONFIG_PATH, help="Path to config.json")
) -> None:
    """Check server connectivity via /system_stats."""
    cfg = _load_config(config)
    base = str(cfg.server_url).rstrip("/")

    with httpx.Client(timeout=20.0) as client:
        r = client.get(f"{base}/system_stats")
        r.raise_for_status()
        payload = r.json()

    typer.echo("Connected to ComfyUI")
    typer.echo(json.dumps(payload, indent=2))


@app.command("send")
def send_prompt(
    prompt_file: Path = typer.Argument(
        ..., exists=True, readable=True, help="Path to prompt/workflow JSON"
    ),
    config: Path = typer.Option(CONFIG_PATH, help="Path to config.json"),
    client_id: str | None = typer.Option(None, help="Optional ComfyUI client_id"),
    positive_prompt: str | None = typer.Option(
        None, "--prompt", help="Override positive prompt text"
    ),
    mesh_seed: int | None = typer.Option(None, help="Override Trellis mesh seed"),
    target_face_num: int | None = typer.Option(None, help="Override target face count"),
    filename_prefix: str | None = typer.Option(
        None, help="Override output filename prefix"
    ),
    texture_seed: int | None = typer.Option(None, help="Override Trellis texture seed"),
    dry_run: bool = typer.Option(False, help="Build payload but do not POST"),
) -> None:
    """Submit a prompt JSON file to ComfyUI /prompt."""
    cfg = _load_config(config)
    base = str(cfg.server_url).rstrip("/")

    prompt = _load_prompt_from_file(prompt_file)
    changes = _apply_overrides(
        prompt,
        positive_prompt=positive_prompt,
        mesh_seed=mesh_seed,
        target_face_num=target_face_num,
        filename_prefix=filename_prefix,
        texture_seed=texture_seed,
    )

    if changes:
        typer.echo("Applied overrides:")
        for c in changes:
            typer.echo(f"- {c}")

    payload: dict[str, Any] = {
        "prompt": prompt,
        "client_id": client_id or str(uuid.uuid4()),
    }

    if dry_run:
        typer.echo(json.dumps(payload, indent=2))
        return

    with httpx.Client(timeout=60.0) as client:
        r = client.post(f"{base}/prompt", json=payload)
        r.raise_for_status()
        result = r.json()

    typer.echo(json.dumps(result, indent=2))


def _get_history_item(
    client: httpx.Client, base: str, prompt_id: str
) -> dict[str, Any] | None:
    r = client.get(f"{base}/history/{prompt_id}")
    r.raise_for_status()
    payload = r.json()
    if isinstance(payload, dict):
        # Sometimes response is {prompt_id: {...}}, sometimes direct object.
        if prompt_id in payload and isinstance(payload[prompt_id], dict):
            return payload[prompt_id]
        if "outputs" in payload:
            return payload
    return None


def _extract_glb_refs(history_item: dict[str, Any]) -> list[str]:
    return _extract_file_refs(history_item, GLB_EXTENSIONS)


def _extract_file_refs(history_item: dict[str, Any], extensions: set[str]) -> list[str]:
    refs: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, str):
            if Path(value).suffix.lower() in extensions:
                refs.append(value)
            return

        if isinstance(value, dict):
            filename = value.get("filename")
            if (
                isinstance(filename, str)
                and Path(filename).suffix.lower() in extensions
            ):
                subfolder = value.get("subfolder")
                if isinstance(subfolder, str) and subfolder.strip():
                    refs.append(f"{subfolder}/{filename}")
                else:
                    refs.append(filename)
                return

            for nested in value.values():
                collect(nested)
            return

        if isinstance(value, list):
            for item in value:
                collect(item)

    outputs = history_item.get("outputs", {})
    if not isinstance(outputs, dict):
        return refs

    for node_data in outputs.values():
        collect(node_data)
    return refs


def _download_glb(
    client: httpx.Client, base: str, glb_ref: str, out_path: Path
) -> None:
    _download_ref(client, base, glb_ref, out_path)


def _download_ref(
    client: httpx.Client, base: str, file_ref: str, out_path: Path
) -> None:
    if file_ref.startswith("http://") or file_ref.startswith("https://"):
        resp = client.get(file_ref)
        resp.raise_for_status()
        out_path.write_bytes(resp.content)
        return

    # Try ComfyUI /view endpoint with output type.
    ref_path = Path(file_ref)
    params: dict[str, str] = {"filename": ref_path.name, "type": "output"}
    if ref_path.parent.as_posix() not in ("", "."):
        params["subfolder"] = ref_path.parent.as_posix()

    query = urlencode(params)
    view_url = f"{base}/view?{query}"
    resp = client.get(view_url)
    resp.raise_for_status()
    out_path.write_bytes(resp.content)


def _raise_for_history_error(prompt_id: str, history_item: dict[str, Any]) -> None:
    status = history_item.get("status")
    if not isinstance(status, dict):
        return

    error_payload: dict[str, Any] | None = None
    messages = status.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if (
                isinstance(message, list)
                and len(message) == 2
                and message[0] == "execution_error"
                and isinstance(message[1], dict)
            ):
                error_payload = message[1]
                break

    incomplete = status.get("completed") is False
    if (
        status.get("status_str") != "error"
        and error_payload is None
        and not incomplete
    ):
        return

    details = error_payload or {}
    node = details.get("node_type") or details.get("node_id") or "unknown node"
    exception_message = details.get("exception_message") or (
        "history marked execution incomplete"
        if incomplete
        else "unknown execution error"
    )
    raise typer.BadParameter(
        f"ComfyUI prompt {prompt_id} failed in {node}: {exception_message}"
    )


async def _wait_for_completion(
    base: str,
    prompt_id: str,
    poll_interval: float,
    timeout: float,
    client_id: str | None = None,
    verbose: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    elapsed = 0.0
    stop_event = asyncio.Event()
    ws_task: asyncio.Task[None] | None = None
    if client_id is not None:
        ws_task = asyncio.create_task(
            _stream_ws_progress(base, client_id, prompt_id, stop_event)
        )

    async with httpx.AsyncClient(timeout=60.0) as aclient:
        while elapsed <= timeout:
            q = await aclient.get(f"{base}/queue")
            q.raise_for_status()
            queue_state = q.json()

            h = await aclient.get(f"{base}/history/{prompt_id}")
            h.raise_for_status()
            history_payload = h.json()

            history_item: dict[str, Any] | None = None
            if isinstance(history_payload, dict):
                if prompt_id in history_payload and isinstance(
                    history_payload[prompt_id], dict
                ):
                    history_item = history_payload[prompt_id]
                elif "outputs" in history_payload:
                    history_item = history_payload

            if history_item is not None:
                stop_event.set()
                if ws_task is not None:
                    await ws_task
                _raise_for_history_error(prompt_id, history_item)
                return (
                    queue_state if isinstance(queue_state, dict) else {}
                ), history_item

            if verbose:
                running = (
                    queue_state.get("queue_running", [])
                    if isinstance(queue_state, dict)
                    else []
                )
                pending = (
                    queue_state.get("queue_pending", [])
                    if isinstance(queue_state, dict)
                    else []
                )
                typer.echo(
                    f"Waiting... running={len(running)} pending={len(pending)} elapsed={int(elapsed)}s"
                )
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

    stop_event.set()
    if ws_task is not None:
        await ws_task

    raise typer.BadParameter(f"Timed out waiting for prompt_id={prompt_id}")


def _download_from_history(
    base: str, prompt_id: str, history_item: dict[str, Any], out_dir: Path
) -> list[Path]:
    return _download_from_history_by_ext(
        base, prompt_id, history_item, out_dir, GLB_EXTENSIONS
    )


def _download_from_history_by_ext(
    base: str,
    prompt_id: str,
    history_item: dict[str, Any],
    out_dir: Path,
    extensions: set[str],
) -> list[Path]:
    refs = _extract_file_refs(history_item, extensions)
    if not refs:
        return []

    out_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[Path] = []
    with httpx.Client(timeout=120.0) as client:
        for ref in refs:
            default_suffix = next(iter(extensions), ".bin")
            filename = Path(ref).name or f"{prompt_id}{default_suffix}"
            dest = out_dir / filename
            _download_ref(client, base, ref, dest)
            downloaded.append(dest)
    return downloaded


def _require_downloaded_artifacts(
    *,
    prompt_id: str,
    downloaded: list[Path],
    extensions: set[str],
    missing_hint: str | None = None,
) -> list[Path]:
    if downloaded:
        return downloaded
    expected = ", ".join(sorted(extensions)) or "requested"
    hint = f"; {missing_hint}" if missing_hint else ""
    raise typer.BadParameter(
        f"ComfyUI prompt {prompt_id} produced no expected artifact ({expected}){hint}"
    )


def _submit_wait_and_download(
    *,
    base: str,
    prompt: dict[str, Any],
    client_id: str | None,
    poll_interval: float,
    timeout: float,
    out_dir: Path,
    extensions: set[str],
    verbose: bool = False,
) -> list[Path]:
    resolved_client_id = client_id or str(uuid.uuid4())
    result = _submit_prompt(base, prompt, resolved_client_id)
    prompt_id = result.get("prompt_id")
    if not isinstance(prompt_id, str):
        raise typer.BadParameter(f"Unexpected /prompt response: {json.dumps(result)}")

    typer.echo(json.dumps(result, indent=2))
    queue_state, history_item = asyncio.run(
        _wait_for_completion(
            base,
            prompt_id,
            poll_interval,
            timeout,
            client_id=resolved_client_id,
            verbose=verbose,
        )
    )
    downloaded = _require_downloaded_artifacts(
        prompt_id=prompt_id,
        downloaded=_download_from_history_by_ext(
            base, prompt_id, history_item, out_dir, extensions
        ),
        extensions=extensions,
    )
    typer.echo("Prompt completed.")
    typer.echo(json.dumps({"prompt_id": prompt_id, "queue": queue_state}, indent=2))
    return downloaded


@app.command("wait")
def wait_prompt(
    prompt_id: str = typer.Argument(..., help="ComfyUI prompt_id"),
    config: Path = typer.Option(CONFIG_PATH, help="Path to config.json"),
    client_id: str | None = typer.Option(
        None,
        help="Optional ComfyUI client_id for /ws progress updates",
    ),
    poll_interval: float = typer.Option(2.0, min=0.5, help="Polling interval seconds"),
    timeout: float = typer.Option(1800.0, min=1.0, help="Max wait time in seconds"),
    verbose: bool = typer.Option(False, help="Show polling progress logs"),
    download_glb: bool = typer.Option(
        True, help="Download generated GLB when available"
    ),
    out_dir: Path = typer.Option(
        Path("downloads"), help="Directory to write downloaded files"
    ),
) -> None:
    """Poll queue/history until prompt completes; optionally download GLB output."""
    cfg = _load_config(config)
    base = str(cfg.server_url).rstrip("/")

    queue_state, history_item = asyncio.run(
        _wait_for_completion(
            base,
            prompt_id,
            poll_interval,
            timeout,
            client_id=client_id,
            verbose=verbose,
        )
    )
    downloaded: list[Path] = []
    if download_glb:
        downloaded = _require_downloaded_artifacts(
            prompt_id=prompt_id,
            downloaded=_download_from_history(base, prompt_id, history_item, out_dir),
            extensions=GLB_EXTENSIONS,
            missing_hint="rerun with --no-download-glb to wait without downloading",
        )

    typer.echo("Prompt completed.")
    typer.echo(json.dumps({"prompt_id": prompt_id, "queue": queue_state}, indent=2))
    for path in downloaded:
        typer.echo(f"Downloaded {path}")


@app.command("run")
def run_prompt(
    prompt_file: Path = typer.Argument(
        ..., exists=True, readable=True, help="Path to prompt/workflow JSON"
    ),
    config: Path = typer.Option(CONFIG_PATH, help="Path to config.json"),
    client_id: str | None = typer.Option(None, help="Optional ComfyUI client_id"),
    positive_prompt: str | None = typer.Option(
        None, "--prompt", help="Override positive prompt text"
    ),
    mesh_seed: int | None = typer.Option(None, help="Override Trellis mesh seed"),
    target_face_num: int | None = typer.Option(None, help="Override target face count"),
    filename_prefix: str | None = typer.Option(
        None, help="Override output filename prefix"
    ),
    texture_seed: int | None = typer.Option(None, help="Override Trellis texture seed"),
    poll_interval: float = typer.Option(2.0, min=0.5, help="Polling interval seconds"),
    timeout: float = typer.Option(1800.0, min=1.0, help="Max wait time in seconds"),
    verbose: bool = typer.Option(False, help="Show polling progress logs"),
    out_dir: Path = typer.Option(
        Path("downloads"), help="Directory to write downloaded files"
    ),
) -> None:
    """Submit prompt, wait asynchronously, and download GLB outputs."""
    cfg = _load_config(config)
    base = str(cfg.server_url).rstrip("/")

    prompt = _load_prompt_from_file(prompt_file)
    changes = _apply_overrides(
        prompt,
        positive_prompt=positive_prompt,
        mesh_seed=mesh_seed,
        target_face_num=target_face_num,
        filename_prefix=filename_prefix,
        texture_seed=texture_seed,
    )
    if changes:
        typer.echo("Applied overrides:")
        for c in changes:
            typer.echo(f"- {c}")

    downloaded = _submit_wait_and_download(
        base=base,
        prompt=prompt,
        client_id=client_id,
        poll_interval=poll_interval,
        timeout=timeout,
        out_dir=out_dir,
        extensions=GLB_EXTENSIONS,
        verbose=verbose,
    )
    for path in downloaded:
        typer.echo(f"Downloaded {path}")


@app.command("text-to-image")
def text_to_image(
    prompt_text: str = typer.Option(
        ..., "--prompt", help="Text prompt to generate the image"
    ),
    workflow_file: Path = typer.Option(
        DEFAULT_TEXT_TO_IMAGE_WORKFLOW,
        help="Path to qwen_image_2512 API prompt JSON",
    ),
    config: Path = typer.Option(CONFIG_PATH, help="Path to config.json"),
    client_id: str | None = typer.Option(None, help="Optional ComfyUI client_id"),
    seed: int | None = typer.Option(None, help="Override KSampler seed"),
    filename_prefix: str | None = typer.Option(
        None, help="Override SaveImage filename prefix"
    ),
    poll_interval: float = typer.Option(2.0, min=0.5, help="Polling interval seconds"),
    timeout: float = typer.Option(1800.0, min=1.0, help="Max wait time in seconds"),
    verbose: bool = typer.Option(False, help="Show polling progress logs"),
    out_dir: Path = typer.Option(
        Path("downloads"), help="Directory to write downloaded files"
    ),
) -> None:
    """Generate image from text using qwen_image_2512 workflow."""
    cfg = _load_config(config)
    base = str(cfg.server_url).rstrip("/")

    prompt = _load_prompt_from_file(workflow_file)
    changes = _apply_overrides(
        prompt,
        positive_prompt=prompt_text,
        mesh_seed=None,
        target_face_num=None,
        filename_prefix=None,
        texture_seed=None,
    )

    if seed is not None:
        node_id = _set_input_on_first_node_by_class(prompt, "KSampler", "seed", seed)
        if node_id is None:
            raise typer.BadParameter("Could not find KSampler for seed override.")
        changes.append(f"seed={seed} -> node {node_id}")

    if filename_prefix is not None:
        node_id = _set_input_on_first_node_by_class(
            prompt, "SaveImage", "filename_prefix", filename_prefix
        )
        if node_id is None:
            raise typer.BadParameter(
                "Could not find SaveImage for filename_prefix override."
            )
        changes.append(f"filename_prefix={filename_prefix} -> node {node_id}")

    if changes:
        typer.echo("Applied overrides:")
        for c in changes:
            typer.echo(f"- {c}")

    downloaded = _submit_wait_and_download(
        base=base,
        prompt=prompt,
        client_id=client_id,
        poll_interval=poll_interval,
        timeout=timeout,
        out_dir=out_dir,
        extensions=IMAGE_EXTENSIONS,
        verbose=verbose,
    )
    for path in downloaded:
        typer.echo(f"Downloaded {path}")


@app.command("image-text-to-image")
def image_text_to_image(
    image: Path = typer.Option(
        ..., exists=True, readable=True, help="Local input image path"
    ),
    prompt_text: str = typer.Option(..., "--prompt", help="Edit prompt"),
    workflow_file: Path = typer.Option(
        DEFAULT_IMAGE_TEXT_TO_IMAGE_WORKFLOW,
        help="Path to qwen_image_edit_2511 API prompt JSON",
    ),
    config: Path = typer.Option(CONFIG_PATH, help="Path to config.json"),
    client_id: str | None = typer.Option(None, help="Optional ComfyUI client_id"),
    seed: int | None = typer.Option(None, help="Override KSampler seed"),
    filename_prefix: str | None = typer.Option(
        None, help="Override SaveImage filename prefix"
    ),
    poll_interval: float = typer.Option(2.0, min=0.5, help="Polling interval seconds"),
    timeout: float = typer.Option(1800.0, min=1.0, help="Max wait time in seconds"),
    verbose: bool = typer.Option(False, help="Show polling progress logs"),
    out_dir: Path = typer.Option(
        Path("downloads"), help="Directory to write downloaded files"
    ),
) -> None:
    """Edit an image with text prompt using qwen_image_edit_2511 workflow."""
    cfg = _load_config(config)
    base = str(cfg.server_url).rstrip("/")

    prompt = _load_prompt_from_file(workflow_file)
    uploaded_image_ref = _upload_input_image(base, image)
    updated_nodes = _replace_all_load_image_inputs(prompt, uploaded_image_ref)
    if not updated_nodes:
        raise typer.BadParameter(
            "Could not find LoadImage nodes to patch uploaded image."
        )

    changes = _apply_overrides(
        prompt,
        positive_prompt=prompt_text,
        mesh_seed=None,
        target_face_num=None,
        filename_prefix=None,
        texture_seed=None,
    )
    changes.append(f"image={uploaded_image_ref} -> nodes {', '.join(updated_nodes)}")

    if seed is not None:
        node_id = _set_input_on_first_node_by_class(prompt, "KSampler", "seed", seed)
        if node_id is None:
            raise typer.BadParameter("Could not find KSampler for seed override.")
        changes.append(f"seed={seed} -> node {node_id}")

    if filename_prefix is not None:
        node_id = _set_input_on_first_node_by_class(
            prompt, "SaveImage", "filename_prefix", filename_prefix
        )
        if node_id is None:
            raise typer.BadParameter(
                "Could not find SaveImage for filename_prefix override."
            )
        changes.append(f"filename_prefix={filename_prefix} -> node {node_id}")

    typer.echo("Applied overrides:")
    for c in changes:
        typer.echo(f"- {c}")

    downloaded = _submit_wait_and_download(
        base=base,
        prompt=prompt,
        client_id=client_id,
        poll_interval=poll_interval,
        timeout=timeout,
        out_dir=out_dir,
        extensions=IMAGE_EXTENSIONS,
        verbose=verbose,
    )
    for path in downloaded:
        typer.echo(f"Downloaded {path}")


def _subject_scale_label(subject_scale: float) -> str:
    """Return a collision-resistant filename label for a validated scale."""
    return str(subject_scale).replace(".", "p")


@app.command("pad-tpose-image")
def pad_tpose_image(
    image: Path = typer.Option(..., exists=True, readable=True, help="Source T-pose image."),
    output: Path | None = typer.Option(None, help="Output PNG path; defaults beside the source."),
    subject_scale: float = typer.Option(0.65, min=0.1, max=1.0, help="Maximum source extent as a fraction of the square canvas."),
    canvas_size: int = typer.Option(1024, min=64, help="Square output canvas size in pixels."),
    background: str = typer.Option("white", help="Pillow-compatible background color."),
) -> None:
    """Center a T-pose image on a padded square canvas for safer 3D reconstruction."""
    destination = output or image.with_name(f"{image.stem}_padded.png")
    try:
        padded = pad_image_on_canvas(
            image,
            destination,
            subject_scale=subject_scale,
            canvas_size=canvas_size,
            background=background,
        )
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(f"Could not pad image: {exc}") from exc
    typer.echo(f"Padded T-pose image: {padded}")


@app.command("image-to-glb")
def image_to_glb(
    image: Path = typer.Option(
        ..., exists=True, readable=True, help="Local input image path"
    ),
    workflow_file: Path = typer.Option(
        DEFAULT_IMAGE_TO_GLB_WORKFLOW,
        help="Path to img_to_trellis2 API prompt JSON",
    ),
    config: Path = typer.Option(CONFIG_PATH, help="Path to config.json"),
    client_id: str | None = typer.Option(None, help="Optional ComfyUI client_id"),
    mesh_seed: int | None = typer.Option(None, help="Override Trellis mesh seed"),
    target_face_num: int | None = typer.Option(80000, help="Override target face count; default keeps notebook GLBs small"),
    filename_prefix: str | None = typer.Option(
        None, help="Override output filename prefix"
    ),
    texture_seed: int | None = typer.Option(None, help="Override Trellis texture seed"),
    subject_scale: float = typer.Option(1.0, min=0.1, max=1.0, help="Optionally scale the complete source onto a padded square canvas before upload; use 0.65 for T-pose safety."),
    padding_canvas_size: int = typer.Option(1024, min=64, help="Canvas size used when --subject-scale is below 1."),
    padding_background: str = typer.Option("white", help="Background color used for optional source padding."),
    poll_interval: float = typer.Option(2.0, min=0.5, help="Polling interval seconds"),
    timeout: float = typer.Option(1800.0, min=1.0, help="Max wait time in seconds"),
    verbose: bool = typer.Option(False, help="Show polling progress logs"),
    out_dir: Path = typer.Option(
        Path("downloads"), help="Directory to write downloaded files"
    ),
) -> None:
    """Convert image to GLB using img_to_trellis2 workflow."""
    cfg = _load_config(config)
    base = str(cfg.server_url).rstrip("/")

    upload_image = image
    if subject_scale < 1.0:
        scale_label = _subject_scale_label(subject_scale)
        upload_image = out_dir / "preprocessed" / f"{image.stem}_padded_{scale_label}.png"
        try:
            pad_image_on_canvas(
                image,
                upload_image,
                subject_scale=subject_scale,
                canvas_size=padding_canvas_size,
                background=padding_background,
            )
        except (ValueError, OSError) as exc:
            raise typer.BadParameter(f"Could not pad image: {exc}") from exc
        typer.echo(f"Padded input image: {upload_image}")

    prompt = _load_prompt_from_file(workflow_file)
    uploaded_image_ref = _upload_input_image(base, upload_image)
    updated_nodes = _replace_all_load_image_inputs(prompt, uploaded_image_ref)
    if not updated_nodes:
        raise typer.BadParameter(
            "Could not find LoadImage nodes to patch uploaded image."
        )

    changes = _apply_overrides(
        prompt,
        positive_prompt=None,
        mesh_seed=mesh_seed,
        target_face_num=target_face_num,
        filename_prefix=filename_prefix,
        texture_seed=texture_seed,
    )
    changes.append(f"image={uploaded_image_ref} -> nodes {', '.join(updated_nodes)}")
    typer.echo("Applied overrides:")
    for c in changes:
        typer.echo(f"- {c}")

    downloaded = _submit_wait_and_download(
        base=base,
        prompt=prompt,
        client_id=client_id,
        poll_interval=poll_interval,
        timeout=timeout,
        out_dir=out_dir,
        extensions=GLB_EXTENSIONS,
        verbose=verbose,
    )
    for path in downloaded:
        typer.echo(f"Downloaded {path}")


@app.command("rig-glb")
def rig_glb(
    workflow_file: Path = typer.Option(
        DEFAULT_RIG_GLB_WORKFLOW,
        help="Path to rig_glb_mia API prompt JSON",
    ),
    config: Path = typer.Option(CONFIG_PATH, help="Path to config.json"),
    client_id: str | None = typer.Option(None, help="Optional ComfyUI client_id"),
    mesh: str | None = typer.Option(
        None,
        help="Override Hy3DUploadMesh mesh input (ComfyUI-accessible .glb reference)",
    ),
    glb_name: str | None = typer.Option(
        None,
        help="Output GLB base name; defaults to the stem of the input mesh filename",
    ),
    no_fingers: bool | None = typer.Option(
        None,
        help="Override MIAAutoRig no_fingers",
    ),
    use_normal: bool | None = typer.Option(
        None,
        help="Override MIAAutoRig use_normal",
    ),
    reset_to_rest: bool | None = typer.Option(
        None,
        help="Override MIAAutoRig reset_to_rest",
    ),
    target_face_count: int | None = typer.Option(
        80000,
        help="Override MIAAutoRig target_face_count mesh simplification before export; default 80000 preserves Trellis textures in current MIA smokes",
    ),
    embed_textures: bool | None = typer.Option(
        True,
        help="Override MIAAutoRig embed_textures for the intermediate FBX export; enabled by default to preserve textured GLBs",
    ),
    precision: str | None = typer.Option(
        None,
        help="Override MIALoadModel precision (auto, bf16, fp16, fp32)",
    ),
    attn_backend: str | None = typer.Option(
        None,
        help="Override MIALoadModel attention backend (auto, flash_attn, sdpa)",
    ),
    auto_skin: bool = typer.Option(
        True,
        "--auto-skin/--no-auto-skin",
        help="Weld duplicate triangle vertices and replace MIA weights with Blender automatic weights after download.",
    ),
    auto_skin_worker: Path = typer.Option(
        DEFAULT_AUTO_SKIN_WORKER,
        help="Isolated Blender automatic-weight worker script.",
    ),
    bpy_container: str = typer.Option(
        "remesher-comfy3d",
        help="Docker container used for automatic weighting when local Python cannot import bpy.",
    ),
    auto_skin_weld_distance: float = typer.Option(
        1e-6,
        min=1e-12,
        help="Merge-by-distance threshold applied before Blender automatic weights.",
    ),
    max_unweighted_fraction: float = typer.Option(
        0.005,
        min=0.0,
        max=1.0,
        help="Maximum fraction of vertices Blender automatic weights may leave unweighted.",
    ),
    poll_interval: float = typer.Option(2.0, min=0.5, help="Polling interval seconds"),
    timeout: float = typer.Option(1800.0, min=1.0, help="Max wait time in seconds"),
    verbose: bool = typer.Option(False, help="Show polling progress logs"),
    out_dir: Path = typer.Option(
        Path("downloads"), help="Directory to write downloaded files"
    ),
) -> None:
    """Auto-rig a GLB mesh using the MIA workflow and download the resulting GLB."""
    cfg = _load_config(config)
    base = str(cfg.server_url).rstrip("/")

    prompt = _load_prompt_from_file(workflow_file)
    changes: list[str] = []

    if mesh is not None:
        resolved_mesh = mesh
        mesh_path = Path(mesh)
        if mesh_path.exists() and mesh_path.is_file():
            uploaded_mesh_ref = _upload_input_asset(base, mesh_path, label="Mesh")
            resolved_mesh = uploaded_mesh_ref
            changes.append(f"mesh_upload={mesh_path} -> {uploaded_mesh_ref}")

        node_id = _set_input_on_first_node_by_class(
            prompt, "Hy3DUploadMesh", "mesh", resolved_mesh
        )
        if node_id is None:
            raise typer.BadParameter("Could not find Hy3DUploadMesh for mesh override.")
        changes.append(f"mesh={resolved_mesh} -> node {node_id}")

    mesh_node = _find_node_by_class(prompt, "Hy3DUploadMesh")
    if not mesh_node:
        raise typer.BadParameter("Could not find Hy3DUploadMesh node in workflow.")
    mesh_inputs = mesh_node[1].get("inputs")
    mesh_input = mesh_inputs.get("mesh") if isinstance(mesh_inputs, dict) else None
    if not isinstance(mesh_input, str) or not mesh_input.strip():
        raise typer.BadParameter(
            "Could not determine Hy3DUploadMesh mesh input for default glb_name."
        )

    resolved_glb_name = glb_name or Path(mesh_input).stem
    if not resolved_glb_name.strip():
        raise typer.BadParameter("Derived glb_name is empty.")

    node_id = _set_input_on_first_node_by_class(
        prompt, "MIAAutoRig", "fbx_name", resolved_glb_name
    )
    if node_id is None:
        raise typer.BadParameter("Could not find MIAAutoRig for fbx_name override.")
    changes.append(f"fbx_name={resolved_glb_name} -> node {node_id}")

    if no_fingers is not None:
        node_id = _set_input_on_first_node_by_class(
            prompt, "MIAAutoRig", "no_fingers", no_fingers
        )
        if node_id is None:
            raise typer.BadParameter(
                "Could not find MIAAutoRig for no_fingers override."
            )
        changes.append(f"no_fingers={no_fingers} -> node {node_id}")

    if use_normal is not None:
        node_id = _set_input_on_first_node_by_class(
            prompt, "MIAAutoRig", "use_normal", use_normal
        )
        if node_id is None:
            raise typer.BadParameter(
                "Could not find MIAAutoRig for use_normal override."
            )
        changes.append(f"use_normal={use_normal} -> node {node_id}")

    if reset_to_rest is not None:
        node_id = _set_input_on_first_node_by_class(
            prompt, "MIAAutoRig", "reset_to_rest", reset_to_rest
        )
        if node_id is None:
            raise typer.BadParameter(
                "Could not find MIAAutoRig for reset_to_rest override."
            )
        changes.append(f"reset_to_rest={reset_to_rest} -> node {node_id}")

    if target_face_count is not None:
        if target_face_count <= 0:
            raise typer.BadParameter("target_face_count must be positive")
        node_id = _set_input_on_first_node_by_class(
            prompt, "MIAAutoRig", "target_face_count", target_face_count
        )
        if node_id is None:
            raise typer.BadParameter("Could not find MIAAutoRig for target_face_count override.")
        changes.append(f"target_face_count={target_face_count} -> node {node_id}")

    if embed_textures is not None:
        node_id = _set_input_on_first_node_by_class(
            prompt, "MIAAutoRig", "embed_textures", embed_textures
        )
        if node_id is None:
            raise typer.BadParameter("Could not find MIAAutoRig for embed_textures override.")
        changes.append(f"embed_textures={embed_textures} -> node {node_id}")

    if precision is not None:
        if precision not in {"auto", "bf16", "fp16", "fp32"}:
            raise typer.BadParameter("precision must be one of: auto, bf16, fp16, fp32")
        node_id = _set_input_on_first_node_by_class(
            prompt, "MIALoadModel", "precision", precision
        )
        if node_id is None:
            raise typer.BadParameter("Could not find MIALoadModel for precision override.")
        changes.append(f"precision={precision} -> node {node_id}")

    if attn_backend is not None:
        if attn_backend not in {"auto", "flash_attn", "sdpa"}:
            raise typer.BadParameter("attn_backend must be one of: auto, flash_attn, sdpa")
        node_id = _set_input_on_first_node_by_class(
            prompt, "MIALoadModel", "attn_backend", attn_backend
        )
        if node_id is None:
            raise typer.BadParameter("Could not find MIALoadModel for attn_backend override.")
        changes.append(f"attn_backend={attn_backend} -> node {node_id}")

    if changes:
        typer.echo("Applied overrides:")
        for c in changes:
            typer.echo(f"- {c}")

    downloaded = _submit_wait_and_download(
        base=base,
        prompt=prompt,
        client_id=client_id,
        poll_interval=poll_interval,
        timeout=timeout,
        out_dir=out_dir,
        extensions=GLB_EXTENSIONS,
        verbose=verbose,
    )
    downloaded = _postprocess_rig_downloads(
        downloaded,
        auto_skin=auto_skin,
        worker_file=auto_skin_worker,
        bpy_container=bpy_container,
        weld_distance=auto_skin_weld_distance,
        max_unweighted_fraction=max_unweighted_fraction,
    )
    for path in downloaded:
        typer.echo(f"Downloaded {path}")


def _run_worker_command(args: list[str], *, cwd: Path | None = None) -> None:
    """Run an isolated worker and stream output without swallowing failures."""
    try:
        completed = subprocess.run(args, cwd=cwd, text=True, check=False)
    except FileNotFoundError as exc:
        raise typer.BadParameter(f"Worker executable not found: {args[0]}") from exc
    if completed.returncode != 0:
        raise typer.Exit(completed.returncode)


def _python_has_bpy() -> bool:
    completed = subprocess.run(
        [sys.executable, "-c", "import bpy"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode == 0


def _copy_to_container(container: str, source: Path, dest: str) -> None:
    _run_worker_command(
        ["docker", "cp", "--", str(source), f"{container}:{dest}"]
    )


def _copy_from_container(container: str, source: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run_worker_command(
        ["docker", "cp", "--", f"{container}:{source}", str(dest)]
    )


def _validate_docker_container_name(container: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", container):
        raise typer.BadParameter(
            "Invalid Docker container name; expected 1-128 characters using "
            "letters, digits, underscore, period, or hyphen, starting with an "
            "alphanumeric character."
        )


def _docker_bpy_exec_prefix(container: str) -> list[str]:
    """Build a docker exec prefix for a clean isolated Blender process.

    Comfy3D globally preloads Open3D on Linux ARM64 for its static-TLS needs.
    Blender's bundled OpenVDB/TBB libraries are incompatible with that preload,
    so bpy workers must start without inheriting it.
    """

    return ["docker", "exec", "-e", "LD_PRELOAD=", "--", container]


def _run_bpy_worker(
    *,
    worker_file: Path,
    positional_inputs: list[Path],
    positional_outputs: list[Path],
    extra_args: list[str],
    summary_json: Path,
    bpy_container: str,
) -> None:
    """Run a bpy worker locally when possible; otherwise use a Comfy3D container.

    The current RunPod image inherits from Comfy3D, so Blender/bpy should normally
    be available in the local Python environment. Older/local control-image setups
    can still fall back to a named Comfy3D sibling container.
    """
    if _python_has_bpy():
        cmd = [
            sys.executable,
            str(worker_file),
            *[str(path) for path in positional_inputs],
            *[str(path) for path in positional_outputs],
            *extra_args,
            "--summary-json",
            str(summary_json),
        ]
        _run_worker_command(cmd)
        return

    _validate_docker_container_name(bpy_container)
    try:
        subprocess.run(
            ["docker", "inspect", "--", bpy_container],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise typer.BadParameter(
            "Local Python cannot import bpy and the Comfy3D bpy container is not available: "
            f"{bpy_container}. Start it first or pass --bpy-container."
        ) from exc

    remote_dir = f"/tmp/remesher-bpy-worker-{uuid.uuid4().hex}"
    remote_script_dir = f"{remote_dir}/docker/demo-jupyter/scripts"
    remote_worker = f"{remote_script_dir}/{worker_file.name}"
    helper = worker_file.with_name("anatomical_skinning.py")
    remote_inputs = [
        f"{remote_dir}/input_{index}_{source.name}"
        for index, source in enumerate(positional_inputs)
    ]
    remote_outputs = [
        f"{remote_dir}/output_{index}_{dest.name}"
        for index, dest in enumerate(positional_outputs)
    ]
    remote_summary = f"{remote_dir}/{summary_json.name}"
    try:
        _run_worker_command(
            [
                "docker",
                "exec",
                "--",
                bpy_container,
                "mkdir",
                "-p",
                remote_script_dir,
            ]
        )
        _copy_to_container(bpy_container, worker_file, remote_worker)
        if helper.exists():
            _copy_to_container(
                bpy_container, helper, f"{remote_script_dir}/{helper.name}"
            )
        for source, remote_path in zip(
            positional_inputs, remote_inputs, strict=True
        ):
            _copy_to_container(bpy_container, source, remote_path)
        _run_worker_command(
            [
                *_docker_bpy_exec_prefix(bpy_container),
                "python",
                remote_worker,
                *remote_inputs,
                *remote_outputs,
                *extra_args,
                "--summary-json",
                remote_summary,
            ]
        )
    except Exception:
        # The worker writes structured diagnostics before returning non-zero.
        # Recover them before deleting the isolated remote directory.
        try:
            _copy_from_container(bpy_container, remote_summary, summary_json)
        except Exception:
            pass
        raise
    else:
        for remote_path, local_path in zip(remote_outputs, positional_outputs, strict=True):
            _copy_from_container(bpy_container, remote_path, local_path)
        _copy_from_container(bpy_container, remote_summary, summary_json)
    finally:
        subprocess.run(
            [
                "docker",
                "exec",
                "--",
                bpy_container,
                "rm",
                "-rf",
                remote_dir,
            ],
            check=False,
        )


def _move_file_noreplace(source: Path, destination: Path) -> None:
    """Atomically rename a file without replacing an existing destination."""
    if sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise OSError(
                errno.ENOTSUP,
                "libc does not expose renameat2(RENAME_NOREPLACE)",
                str(destination),
            )
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        result = renameat2(
            -100,
            os.fsencode(source),
            -100,
            os.fsencode(destination),
            1,
        )
        if result != 0:
            error_number = ctypes.get_errno()
            raise OSError(
                error_number,
                os.strerror(error_number),
                str(destination),
            )
        return
    if os.name == "nt":
        os.rename(source, destination)
        return
    raise OSError(
        errno.ENOTSUP,
        "Atomic no-replace rename is unsupported on this platform",
        str(destination),
    )


def _publish_file_pair_noreplace(
    *,
    candidate_output: Path,
    output_glb: Path,
    candidate_summary: Path,
    summary_json: Path,
) -> None:
    """Publish GLB first, then its hash-bound summary as the commit marker."""
    try:
        summary = json.loads(candidate_summary.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        raise typer.BadParameter(
            f"Automatic-weight summary is not valid JSON: {candidate_summary}"
        ) from exc
    if not isinstance(summary, dict):
        raise typer.BadParameter(
            f"Automatic-weight summary must be a JSON object: {candidate_summary}"
        )
    expected_sha256 = summary.get("output_sha256")
    if not isinstance(expected_sha256, str):
        raise typer.BadParameter("Automatic-weight summary has no output_sha256")
    digest = hashlib.sha256()
    with candidate_output.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual_sha256 = digest.hexdigest()
    if actual_sha256 != expected_sha256:
        raise typer.BadParameter(
            "Automatic-weight summary hash does not match candidate GLB: "
            f"{expected_sha256} != {actual_sha256}"
        )
    _move_file_noreplace(candidate_output, output_glb)
    _move_file_noreplace(candidate_summary, summary_json)


def _postprocess_rig_downloads(
    downloaded: list[Path],
    *,
    auto_skin: bool,
    worker_file: Path,
    bpy_container: str,
    weld_distance: float,
    max_unweighted_fraction: float,
) -> list[Path]:
    """Replace downloaded MIA weights with Blender automatic weights by default."""
    if not auto_skin:
        return downloaded
    if not math.isfinite(weld_distance) or weld_distance <= 0:
        raise typer.BadParameter(
            "--auto-skin-weld-distance must be finite and greater than 0"
        )
    if not 0 <= max_unweighted_fraction <= 1:
        raise typer.BadParameter(
            "--max-unweighted-fraction must be between 0 and 1"
        )
    if not worker_file.exists() and not worker_file.is_absolute():
        repo_candidate = Path(__file__).resolve().parents[2] / worker_file
        if repo_candidate.exists():
            worker_file = repo_candidate
    if not worker_file.exists() or not worker_file.is_file():
        raise typer.BadParameter(f"Automatic-weight worker not found: {worker_file}")

    for output_glb in downloaded:
        if output_glb.suffix.lower() != ".glb":
            continue
        if not output_glb.exists() or not output_glb.is_file():
            raise typer.BadParameter(f"Downloaded MIA GLB not found: {output_glb}")
        raw_mia = output_glb.with_name(
            f"{output_glb.stem}.mia_raw{output_glb.suffix}"
        )
        summary_json = output_glb.with_name(
            f"{output_glb.stem}.autoskin.json"
        )
        existing = [path for path in (raw_mia, summary_json) if path.exists()]
        if existing:
            raise typer.BadParameter(
                "Refusing to overwrite existing automatic-weight artifact(s): "
                + ", ".join(str(path) for path in existing)
            )

        workspace = Path(
            tempfile.mkdtemp(
                prefix=f".{output_glb.stem}.autoskin-",
                dir=output_glb.parent,
            )
        )
        workspace.chmod(0o700)
        candidate_output = workspace / output_glb.name
        candidate_summary = workspace / summary_json.name
        try:
            try:
                _move_file_noreplace(output_glb, raw_mia)
            except FileExistsError as exc:
                raise typer.BadParameter(
                    f"Refusing to overwrite existing automatic-weight artifact: {raw_mia}"
                ) from exc
            try:
                _run_bpy_worker(
                    worker_file=worker_file,
                    positional_inputs=[raw_mia],
                    positional_outputs=[candidate_output],
                    extra_args=[
                        "--weld-distance",
                        str(weld_distance),
                        "--max-unweighted-fraction",
                        str(max_unweighted_fraction),
                    ],
                    summary_json=candidate_summary,
                    bpy_container=bpy_container,
                )
            except Exception:
                if candidate_summary.exists():
                    try:
                        _move_file_noreplace(candidate_summary, summary_json)
                    except FileExistsError:
                        pass
                raise
            if not candidate_output.exists() or not candidate_output.is_file():
                raise typer.BadParameter(
                    "Automatic-weight worker completed but output was not found: "
                    f"{candidate_output}"
                )
            if not candidate_summary.exists() or not candidate_summary.is_file():
                raise typer.BadParameter(
                    "Automatic-weight worker completed but summary was not found: "
                    f"{candidate_summary}"
                )
            try:
                _publish_file_pair_noreplace(
                    candidate_output=candidate_output,
                    output_glb=output_glb,
                    candidate_summary=candidate_summary,
                    summary_json=summary_json,
                )
            except FileExistsError as exc:
                raise typer.BadParameter(
                    "Refusing to overwrite a concurrently created automatic-weight "
                    f"artifact: {exc.filename}"
                ) from exc
        finally:
            shutil.rmtree(workspace, ignore_errors=True)
        typer.echo(f"Raw MIA GLB: {raw_mia}")
        typer.echo(f"Blender auto-skinned GLB: {output_glb}")
        typer.echo(f"Auto-skin summary: {summary_json}")
    return downloaded


def _cleanup_output_base_name(output_name: str | None, *, default: str) -> str:
    """Normalize a cleanup output basename without permitting directories."""
    candidate = output_name if output_name is not None else default
    if candidate.lower().endswith(".glb"):
        candidate = candidate[:-4]
    if (
        not candidate
        or candidate in {".", ".."}
        or "/" in candidate
        or "\\" in candidate
        or Path(candidate).name != candidate
    ):
        raise ValueError("cleanup output name must be a pure base name")
    return candidate


@app.command("skin-cleanup-glb-local")
def skin_cleanup_glb_local(
    input_glb: Path = typer.Option(..., "--input-glb", help="Rigged GLB to clean"),
    output_name: str = typer.Option(..., help="Output GLB basename without extension"),
    out_dir: Path = typer.Option(Path("downloads"), help="Directory for cleaned GLB and summary JSON"),
    mode: str = typer.Option("conservative", help="Cleanup mode: diagnostic, conservative, motion-diagnostic, or component-repair"),
    repair_zones: str = typer.Option("head_top,head_neck,left_hip,right_hip", help="Comma-separated repair zones"),
    max_fraction_per_zone: float = typer.Option(0.03, min=0.0, help="Maximum repaired vertex fraction per zone"),
    motion_frames: str = typer.Option("0,16,24,32", help="Comma-separated frames for motion diagnostics"),
    max_motion_component_size: int = typer.Option(64, min=1, help="Max connected-component size for motion diagnostics"),
    component_repair_ids: str = typer.Option("", help="Comma-separated connected-component IDs for component-repair mode"),
    component_repair_weights: str = typer.Option("RightUpLeg=0.62,Hips=0.38", help="Comma-separated bone=weight list for component-repair mode"),
    worker_file: Path = typer.Option(Path("docker/demo-jupyter/scripts/anatomical_cleanup_worker.py"), help="Path to isolated cleanup worker script"),
    bpy_container: str = typer.Option("remesher-comfy3d", help="Docker container to use when local Python cannot import bpy"),
    no_validate: bool = typer.Option(False, help="Skip reimport validation in the worker"),
) -> None:
    """Clean anatomical skin weights in a rigged GLB using the isolated bpy worker."""
    if not input_glb.exists() or not input_glb.is_file():
        raise typer.BadParameter(f"Input GLB not found: {input_glb}")
    if not worker_file.exists() or not worker_file.is_file():
        raise typer.BadParameter(f"Worker file not found: {worker_file}")
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        output_base = _cleanup_output_base_name(output_name, default=input_glb.stem)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    output_glb = out_dir / f"{output_base}.glb"
    summary_json = out_dir / f"{output_base}.skin_cleanup.json"
    existing_outputs = [path for path in (output_glb, summary_json) if path.exists()]
    if existing_outputs:
        raise typer.BadParameter(
            "Refusing to overwrite existing cleanup output(s): "
            + ", ".join(str(path) for path in existing_outputs)
        )
    extra_args = [
        "--mode",
        mode,
        "--max-fraction-per-zone",
        str(max_fraction_per_zone),
        "--repair-zones",
        repair_zones,
        "--motion-frames",
        motion_frames,
        "--max-motion-component-size",
        str(max_motion_component_size),
        "--component-repair-ids",
        component_repair_ids,
        "--component-repair-weights",
        component_repair_weights,
    ]
    if no_validate:
        extra_args.append("--no-validate")
    _run_bpy_worker(
        worker_file=worker_file,
        positional_inputs=[input_glb],
        positional_outputs=[output_glb],
        extra_args=extra_args,
        summary_json=summary_json,
        bpy_container=bpy_container,
    )
    missing_outputs = [path for path in (output_glb, summary_json) if not path.exists()]
    if missing_outputs:
        raise typer.BadParameter(
            "Cleanup worker completed but did not create required output(s): "
            + ", ".join(str(path) for path in missing_outputs)
        )
    typer.echo(f"Cleaned GLB: {output_glb}")
    typer.echo(f"Summary JSON: {summary_json}")


@app.command("retarget-glb")
def retarget_glb(
    rigged_glb: Path = typer.Option(..., "--rigged-glb", help="Rigged GLB to animate"),
    animation: Path = typer.Option(..., "--animation", help="Mixamo FBX animation source"),
    glb_name: str = typer.Option(..., help="Output GLB basename without extension"),
    out_dir: Path = typer.Option(Path("downloads"), help="Directory for animated GLB and summary JSON"),
    worker_file: Path = typer.Option(Path("docker/demo-jupyter/scripts/arp_retarget_worker.py"), help="Path to isolated ARP retarget worker script"),
    bpy_container: str = typer.Option("remesher-comfy3d", help="Docker container to use when local Python cannot import bpy/Auto-Rig Pro"),
    frame_start: int | None = typer.Option(None, help="Override animation start frame"),
    frame_end: int | None = typer.Option(None, help="Override animation end frame; <=0 uses source action end"),
    no_validate: bool = typer.Option(False, help="Skip reimport validation in the worker"),
) -> None:
    """Retarget a Mixamo FBX animation onto a rigged GLB using the isolated ARP worker."""
    if not rigged_glb.exists() or not rigged_glb.is_file():
        raise typer.BadParameter(f"Rigged GLB not found: {rigged_glb}")
    if not animation.exists() or not animation.is_file():
        raise typer.BadParameter(f"Animation FBX not found: {animation}")
    if not worker_file.exists() or not worker_file.is_file():
        raise typer.BadParameter(f"Worker file not found: {worker_file}")
    out_dir.mkdir(parents=True, exist_ok=True)
    output_glb = out_dir / f"{glb_name}.glb"
    summary_json = out_dir / f"{glb_name}.retarget.json"
    extra_args = []
    if frame_start is not None:
        extra_args.extend(["--frame-start", str(frame_start)])
    if frame_end is not None:
        extra_args.extend(["--frame-end", str(frame_end)])
    if no_validate:
        extra_args.append("--no-validate")
    _run_bpy_worker(
        worker_file=worker_file,
        positional_inputs=[rigged_glb, animation],
        positional_outputs=[output_glb],
        extra_args=extra_args,
        summary_json=summary_json,
        bpy_container=bpy_container,
    )
    if not output_glb.exists():
        raise typer.BadParameter(f"Retarget worker completed but did not create {output_glb}")
    typer.echo(f"Animated GLB: {output_glb}")
    typer.echo(f"Summary JSON: {summary_json}")


@app.command("text-to-glb")
def text_to_glb(
    prompt_text: str = typer.Option(
        ..., "--prompt", help="Text prompt to generate the source image"
    ),
    text_workflow_file: Path = typer.Option(
        DEFAULT_TEXT_TO_IMAGE_WORKFLOW,
        help="Path to text-to-image API prompt JSON",
    ),
    glb_workflow_file: Path = typer.Option(
        DEFAULT_IMAGE_TO_GLB_WORKFLOW,
        help="Path to image-to-glb API prompt JSON",
    ),
    config: Path = typer.Option(CONFIG_PATH, help="Path to config.json"),
    client_id: str | None = typer.Option(None, help="Optional ComfyUI client_id"),
    seed: int | None = typer.Option(None, help="Override KSampler seed for text stage"),
    image_filename_prefix: str | None = typer.Option(
        None,
        help="Override SaveImage filename prefix for text stage",
    ),
    mesh_seed: int | None = typer.Option(None, help="Override Trellis mesh seed"),
    target_face_num: int | None = typer.Option(80000, help="Override target face count; default keeps notebook GLBs small"),
    filename_prefix: str | None = typer.Option(
        None, help="Override Trellis export filename prefix"
    ),
    texture_seed: int | None = typer.Option(None, help="Override Trellis texture seed"),
    poll_interval: float = typer.Option(2.0, min=0.5, help="Polling interval seconds"),
    timeout: float = typer.Option(1800.0, min=1.0, help="Max wait time in seconds"),
    verbose: bool = typer.Option(False, help="Show polling progress logs"),
    out_dir: Path = typer.Option(
        Path("downloads"), help="Directory to write downloaded files"
    ),
) -> None:
    """Generate a GLB end-to-end: text-to-image, then image-to-glb."""
    cfg = _load_config(config)
    base = str(cfg.server_url).rstrip("/")

    text_out_dir = out_dir / "text_to_glb_images"
    glb_out_dir = out_dir / "text_to_glb_glb"

    typer.echo("Stage 1/2: text-to-image")
    text_prompt = _load_prompt_from_file(text_workflow_file)
    text_changes = _apply_overrides(
        text_prompt,
        positive_prompt=prompt_text,
        mesh_seed=None,
        target_face_num=None,
        filename_prefix=None,
        texture_seed=None,
    )
    if seed is not None:
        node_id = _set_input_on_first_node_by_class(
            text_prompt, "KSampler", "seed", seed
        )
        if node_id is None:
            raise typer.BadParameter("Could not find KSampler for seed override.")
        text_changes.append(f"seed={seed} -> node {node_id}")
    if image_filename_prefix is not None:
        node_id = _set_input_on_first_node_by_class(
            text_prompt, "SaveImage", "filename_prefix", image_filename_prefix
        )
        if node_id is None:
            raise typer.BadParameter(
                "Could not find SaveImage for image_filename_prefix override."
            )
        text_changes.append(
            f"image_filename_prefix={image_filename_prefix} -> node {node_id}"
        )

    if text_changes:
        typer.echo("Applied overrides:")
        for c in text_changes:
            typer.echo(f"- {c}")

    images = _submit_wait_and_download(
        base=base,
        prompt=text_prompt,
        client_id=client_id,
        poll_interval=poll_interval,
        timeout=timeout,
        out_dir=text_out_dir,
        extensions=IMAGE_EXTENSIONS,
        verbose=verbose,
    )
    if not images:
        raise typer.BadParameter(
            "No image output reference found in text-to-image stage."
        )

    source_image = images[0]
    typer.echo(f"Using image for GLB stage: {source_image}")

    typer.echo("Stage 2/2: image-to-glb")
    glb_prompt = _load_prompt_from_file(glb_workflow_file)
    uploaded_image_ref = _upload_input_image(base, source_image)
    updated_nodes = _replace_all_load_image_inputs(glb_prompt, uploaded_image_ref)
    if not updated_nodes:
        raise typer.BadParameter(
            "Could not find LoadImage nodes to patch uploaded image for GLB stage."
        )

    glb_changes = _apply_overrides(
        glb_prompt,
        positive_prompt=None,
        mesh_seed=mesh_seed,
        target_face_num=target_face_num,
        filename_prefix=filename_prefix,
        texture_seed=texture_seed,
    )
    glb_changes.append(
        f"image={uploaded_image_ref} -> nodes {', '.join(updated_nodes)}"
    )
    typer.echo("Applied overrides:")
    for c in glb_changes:
        typer.echo(f"- {c}")

    glb_downloads = _submit_wait_and_download(
        base=base,
        prompt=glb_prompt,
        client_id=client_id,
        poll_interval=poll_interval,
        timeout=timeout,
        out_dir=glb_out_dir,
        extensions=GLB_EXTENSIONS,
        verbose=verbose,
    )
    if not glb_downloads:
        typer.echo("No GLB reference found in history outputs.")
        return
    for path in glb_downloads:
        typer.echo(f"Downloaded {path}")


@app.command("text-to-rigged-glb")
def text_to_rigged_glb(
    prompt_text: str = typer.Option(
        ..., "--prompt", help="Text prompt to generate the source image"
    ),
    text_workflow_file: Path = typer.Option(
        DEFAULT_TEXT_TO_IMAGE_WORKFLOW,
        help="Path to text-to-image API prompt JSON",
    ),
    glb_workflow_file: Path = typer.Option(
        DEFAULT_IMAGE_TO_GLB_WORKFLOW,
        help="Path to image-to-glb API prompt JSON",
    ),
    rig_workflow_file: Path = typer.Option(
        DEFAULT_RIG_GLB_WORKFLOW,
        help="Path to rig_glb_mia API prompt JSON",
    ),
    config: Path = typer.Option(CONFIG_PATH, help="Path to config.json"),
    client_id: str | None = typer.Option(None, help="Optional ComfyUI client_id"),
    seed: int | None = typer.Option(None, help="Override KSampler seed for text stage"),
    image_filename_prefix: str | None = typer.Option(
        None,
        help="Override SaveImage filename prefix for text stage",
    ),
    mesh_seed: int | None = typer.Option(None, help="Override Trellis mesh seed"),
    target_face_num: int | None = typer.Option(80000, help="Override target face count; default keeps generated GLBs small"),
    filename_prefix: str | None = typer.Option(
        None, help="Override Trellis export filename prefix"
    ),
    texture_seed: int | None = typer.Option(None, help="Override Trellis texture seed"),
    glb_name: str | None = typer.Option(
        None,
        help="Rigged GLB base name; defaults to the stem of the generated GLB",
    ),
    no_fingers: bool | None = typer.Option(
        None,
        help="Override MIAAutoRig no_fingers",
    ),
    use_normal: bool | None = typer.Option(
        None,
        help="Override MIAAutoRig use_normal",
    ),
    reset_to_rest: bool | None = typer.Option(
        None,
        help="Override MIAAutoRig reset_to_rest",
    ),
    target_face_count: int | None = typer.Option(
        80000,
        help="Override MIAAutoRig target_face_count mesh simplification before export; default 80000 preserves Trellis textures in current MIA smokes",
    ),
    embed_textures: bool | None = typer.Option(
        True,
        help="Override MIAAutoRig embed_textures for the intermediate FBX export; enabled by default to preserve textured GLBs",
    ),
    precision: str | None = typer.Option(
        None,
        help="Override MIALoadModel precision (auto, bf16, fp16, fp32)",
    ),
    attn_backend: str | None = typer.Option(
        None,
        help="Override MIALoadModel attention backend (auto, flash_attn, sdpa)",
    ),
    auto_skin: bool = typer.Option(
        True,
        "--auto-skin/--no-auto-skin",
        help="Weld duplicate triangle vertices and replace MIA weights with Blender automatic weights after download.",
    ),
    auto_skin_worker: Path = typer.Option(
        DEFAULT_AUTO_SKIN_WORKER,
        help="Isolated Blender automatic-weight worker script.",
    ),
    bpy_container: str = typer.Option(
        "remesher-comfy3d",
        help="Docker container used for automatic weighting when local Python cannot import bpy.",
    ),
    auto_skin_weld_distance: float = typer.Option(
        1e-6,
        min=1e-12,
        help="Merge-by-distance threshold applied before Blender automatic weights.",
    ),
    max_unweighted_fraction: float = typer.Option(
        0.005,
        min=0.0,
        max=1.0,
        help="Maximum fraction of vertices Blender automatic weights may leave unweighted.",
    ),
    poll_interval: float = typer.Option(2.0, min=0.5, help="Polling interval seconds"),
    timeout: float = typer.Option(1800.0, min=1.0, help="Max wait time in seconds"),
    verbose: bool = typer.Option(False, help="Show polling progress logs"),
    out_dir: Path = typer.Option(
        Path("downloads"), help="Directory to write downloaded files"
    ),
) -> None:
    """Generate and rig end-to-end: text-to-image, image-to-glb, then rig-glb."""
    cfg = _load_config(config)
    base = str(cfg.server_url).rstrip("/")

    text_out_dir = out_dir / "text_to_rigged_glb_images"
    glb_out_dir = out_dir / "text_to_rigged_glb_glb"
    rig_out_dir = out_dir / "text_to_rigged_glb_rigged"

    typer.echo("Stage 1/3: text-to-image")
    text_prompt = _load_prompt_from_file(text_workflow_file)
    text_changes = _apply_overrides(
        text_prompt,
        positive_prompt=prompt_text,
        mesh_seed=None,
        target_face_num=None,
        filename_prefix=None,
        texture_seed=None,
    )
    if seed is not None:
        node_id = _set_input_on_first_node_by_class(
            text_prompt, "KSampler", "seed", seed
        )
        if node_id is None:
            raise typer.BadParameter("Could not find KSampler for seed override.")
        text_changes.append(f"seed={seed} -> node {node_id}")
    if image_filename_prefix is not None:
        node_id = _set_input_on_first_node_by_class(
            text_prompt, "SaveImage", "filename_prefix", image_filename_prefix
        )
        if node_id is None:
            raise typer.BadParameter(
                "Could not find SaveImage for image_filename_prefix override."
            )
        text_changes.append(
            f"image_filename_prefix={image_filename_prefix} -> node {node_id}"
        )

    if text_changes:
        typer.echo("Applied overrides:")
        for c in text_changes:
            typer.echo(f"- {c}")

    images = _submit_wait_and_download(
        base=base,
        prompt=text_prompt,
        client_id=client_id,
        poll_interval=poll_interval,
        timeout=timeout,
        out_dir=text_out_dir,
        extensions=IMAGE_EXTENSIONS,
        verbose=verbose,
    )
    if not images:
        raise typer.BadParameter(
            "No image output reference found in text-to-image stage."
        )
    source_image = images[0]
    typer.echo(f"Using image for GLB stage: {source_image}")

    typer.echo("Stage 2/3: image-to-glb")
    glb_prompt = _load_prompt_from_file(glb_workflow_file)
    uploaded_image_ref = _upload_input_image(base, source_image)
    updated_nodes = _replace_all_load_image_inputs(glb_prompt, uploaded_image_ref)
    if not updated_nodes:
        raise typer.BadParameter(
            "Could not find LoadImage nodes to patch uploaded image for GLB stage."
        )

    glb_changes = _apply_overrides(
        glb_prompt,
        positive_prompt=None,
        mesh_seed=mesh_seed,
        target_face_num=target_face_num,
        filename_prefix=filename_prefix,
        texture_seed=texture_seed,
    )
    glb_changes.append(
        f"image={uploaded_image_ref} -> nodes {', '.join(updated_nodes)}"
    )
    typer.echo("Applied overrides:")
    for c in glb_changes:
        typer.echo(f"- {c}")

    stage2_client_id = client_id or str(uuid.uuid4())
    stage2_result = _submit_prompt(base, glb_prompt, stage2_client_id)
    stage2_prompt_id = stage2_result.get("prompt_id")
    if not isinstance(stage2_prompt_id, str):
        raise typer.BadParameter(
            f"Unexpected /prompt response for image-to-glb stage: {json.dumps(stage2_result)}"
        )
    typer.echo(json.dumps(stage2_result, indent=2))
    queue_state, history_item = asyncio.run(
        _wait_for_completion(
            base,
            stage2_prompt_id,
            poll_interval,
            timeout,
            client_id=stage2_client_id,
            verbose=verbose,
        )
    )
    typer.echo("Image-to-GLB stage completed.")
    typer.echo(
        json.dumps({"prompt_id": stage2_prompt_id, "queue": queue_state}, indent=2)
    )

    glb_refs = _extract_file_refs(history_item, GLB_EXTENSIONS)
    if not glb_refs:
        raise typer.BadParameter(
            "No GLB reference found in image-to-glb stage outputs."
        )
    source_glb_ref = glb_refs[0]
    typer.echo(f"Using GLB for rig stage: {source_glb_ref}")

    stage2_downloads = _download_from_history_by_ext(
        base,
        stage2_prompt_id,
        history_item,
        glb_out_dir,
        GLB_EXTENSIONS,
    )
    if not stage2_downloads:
        raise typer.BadParameter("Failed to download GLB artifact for rig stage.")

    downloaded_glb = stage2_downloads[0]
    uploaded_glb_ref = _upload_input_asset(base, downloaded_glb, label="Mesh")

    for path in stage2_downloads:
        typer.echo(f"Downloaded {path}")
    typer.echo(f"Uploaded GLB for rig stage: {uploaded_glb_ref}")

    typer.echo("Stage 3/3: rig-glb")
    rig_prompt = _load_prompt_from_file(rig_workflow_file)
    rig_changes: list[str] = []

    rig_mesh_node_id = _set_input_on_first_node_by_class(
        rig_prompt, "Hy3DUploadMesh", "mesh", uploaded_glb_ref
    )
    if rig_mesh_node_id is None:
        raise typer.BadParameter(
            "Could not find Hy3DUploadMesh for mesh override in rig stage."
        )
    rig_changes.append(f"mesh={uploaded_glb_ref} -> node {rig_mesh_node_id}")

    resolved_glb_name = glb_name or downloaded_glb.stem
    if not resolved_glb_name.strip():
        raise typer.BadParameter("Derived glb_name is empty for rig stage.")

    rig_name_node_id = _set_input_on_first_node_by_class(
        rig_prompt, "MIAAutoRig", "fbx_name", resolved_glb_name
    )
    if rig_name_node_id is None:
        raise typer.BadParameter("Could not find MIAAutoRig for fbx_name override.")
    rig_changes.append(f"fbx_name={resolved_glb_name} -> node {rig_name_node_id}")

    if no_fingers is not None:
        node_id = _set_input_on_first_node_by_class(
            rig_prompt, "MIAAutoRig", "no_fingers", no_fingers
        )
        if node_id is None:
            raise typer.BadParameter(
                "Could not find MIAAutoRig for no_fingers override."
            )
        rig_changes.append(f"no_fingers={no_fingers} -> node {node_id}")

    if use_normal is not None:
        node_id = _set_input_on_first_node_by_class(
            rig_prompt, "MIAAutoRig", "use_normal", use_normal
        )
        if node_id is None:
            raise typer.BadParameter(
                "Could not find MIAAutoRig for use_normal override."
            )
        rig_changes.append(f"use_normal={use_normal} -> node {node_id}")

    if reset_to_rest is not None:
        node_id = _set_input_on_first_node_by_class(
            rig_prompt, "MIAAutoRig", "reset_to_rest", reset_to_rest
        )
        if node_id is None:
            raise typer.BadParameter(
                "Could not find MIAAutoRig for reset_to_rest override."
            )
        rig_changes.append(f"reset_to_rest={reset_to_rest} -> node {node_id}")

    if target_face_count is not None:
        if target_face_count <= 0:
            raise typer.BadParameter("target_face_count must be positive")
        node_id = _set_input_on_first_node_by_class(
            rig_prompt, "MIAAutoRig", "target_face_count", target_face_count
        )
        if node_id is None:
            raise typer.BadParameter("Could not find MIAAutoRig for target_face_count override.")
        rig_changes.append(f"target_face_count={target_face_count} -> node {node_id}")

    if embed_textures is not None:
        node_id = _set_input_on_first_node_by_class(
            rig_prompt, "MIAAutoRig", "embed_textures", embed_textures
        )
        if node_id is None:
            raise typer.BadParameter("Could not find MIAAutoRig for embed_textures override.")
        rig_changes.append(f"embed_textures={embed_textures} -> node {node_id}")

    if precision is not None:
        if precision not in {"auto", "bf16", "fp16", "fp32"}:
            raise typer.BadParameter("precision must be one of: auto, bf16, fp16, fp32")
        node_id = _set_input_on_first_node_by_class(
            rig_prompt, "MIALoadModel", "precision", precision
        )
        if node_id is None:
            raise typer.BadParameter("Could not find MIALoadModel for precision override.")
        rig_changes.append(f"precision={precision} -> node {node_id}")

    if attn_backend is not None:
        if attn_backend not in {"auto", "flash_attn", "sdpa"}:
            raise typer.BadParameter("attn_backend must be one of: auto, flash_attn, sdpa")
        node_id = _set_input_on_first_node_by_class(
            rig_prompt, "MIALoadModel", "attn_backend", attn_backend
        )
        if node_id is None:
            raise typer.BadParameter("Could not find MIALoadModel for attn_backend override.")
        rig_changes.append(f"attn_backend={attn_backend} -> node {node_id}")

    typer.echo("Applied overrides:")
    for c in rig_changes:
        typer.echo(f"- {c}")

    rigged_downloads = _submit_wait_and_download(
        base=base,
        prompt=rig_prompt,
        client_id=client_id,
        poll_interval=poll_interval,
        timeout=timeout,
        out_dir=rig_out_dir,
        extensions=GLB_EXTENSIONS,
        verbose=verbose,
    )
    if not rigged_downloads:
        typer.echo("No GLB reference found in rig stage history outputs.")
        return
    rigged_downloads = _postprocess_rig_downloads(
        rigged_downloads,
        auto_skin=auto_skin,
        worker_file=auto_skin_worker,
        bpy_container=bpy_container,
        weld_distance=auto_skin_weld_distance,
        max_unweighted_fraction=max_unweighted_fraction,
    )
    for path in rigged_downloads:
        typer.echo(f"Downloaded {path}")


config_app = typer.Typer(help="Manage local config")
app.add_typer(config_app, name="config")


@config_app.command("init")
def config_init(
    server_url: str = typer.Option(
        "http://mgmacpro2019:8188/",
        help="ComfyUI server URL",
    ),
    out: Path = typer.Option(CONFIG_PATH, help="Output config path"),
    force: bool = typer.Option(False, help="Overwrite existing config"),
) -> None:
    """Create config.json for this project."""
    if out.exists() and not force:
        raise typer.BadParameter(f"{out} already exists. Pass --force to overwrite.")

    cfg = AppConfig.model_validate({"server_url": server_url})
    out.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(f"Wrote {out}")


def _worker_output_candidates(
    *,
    input_dir: Path,
    subfolder: str,
    filename: str,
) -> tuple[Path, Path]:
    output_root = input_dir.parent / "output"
    return (
        output_root / "comfyui" / subfolder / filename,
        output_root / subfolder / filename,
    )


def _clear_worker_output_candidates(
    *,
    input_dir: Path,
    subfolder: str,
    filenames: tuple[str, ...],
) -> None:
    """Remove stale worker intermediates before launching a new invocation."""
    for filename in filenames:
        for candidate in _worker_output_candidates(
            input_dir=input_dir,
            subfolder=subfolder,
            filename=filename,
        ):
            try:
                candidate.unlink(missing_ok=True)
            except PermissionError:
                # Docker-created files may be root-owned; the active command
                # also clears them through docker exec before worker launch.
                continue


def _recover_worker_output(
    *,
    input_dir: Path,
    subfolder: str,
    filename: str,
    destination: Path,
) -> Path | None:
    """Copy a worker artifact from either supported Comfy host-mount layout."""
    import shutil

    candidates = [
        candidate
        for candidate in _worker_output_candidates(
            input_dir=input_dir,
            subfolder=subfolder,
            filename=filename,
        )
        if candidate.exists()
    ]
    if not candidates:
        return None
    destination_resolved = destination.resolve()
    if destination.exists():
        matching_destination = [
            candidate
            for candidate in candidates
            if candidate.resolve() == destination_resolved
        ]
        if not matching_destination:
            return None
        candidate = max(matching_destination, key=lambda path: path.stat().st_mtime_ns)
    else:
        candidate = max(candidates, key=lambda path: path.stat().st_mtime_ns)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if candidate.resolve() != destination_resolved:
        shutil.copy2(candidate, destination)
    return candidate


@app.command("skin-cleanup-glb")
def skin_cleanup_glb(
    input_glb: Path = typer.Option(..., "--input-glb", "--mesh", help="Rigged or animated GLB to clean."),
    output_name: str | None = typer.Option(None, "--output-name", help="Output GLB base name."),
    worker_file: Path = typer.Option(DEFAULT_SKIN_CLEANUP_WORKER, help="Anatomical cleanup worker script to stage into the Comfy3D container."),
    container: str = typer.Option("remesher-comfy3d", help="Docker container with bpy + UniRig installed."),
    input_dir: Path = typer.Option(Path("workspace/input"), help="Host/Jupyter input directory mounted to /app/comfy/input."),
    out_dir: Path = typer.Option(Path("workspace/output/rigged"), help="Host/Jupyter output directory for cleaned GLBs."),
    mode: str = typer.Option("conservative", help="Cleanup mode: diagnostic, conservative, motion-diagnostic, component-repair."),
    repair_zones: str = typer.Option("head_top,head_neck", help="Comma-separated zones to repair. Head zones are the notebook default."),
    max_fraction_per_zone: float = typer.Option(0.03, help="Safety cap for conservative rewrites per zone."),
    validate: bool = typer.Option(True, help="Re-import exported GLB and validate structure."),
) -> None:
    """Run conservative anatomical skin-weight cleanup on a GLB in the Comfy3D container."""
    import shutil
    import subprocess

    if not input_glb.exists():
        raise typer.BadParameter(f"Input GLB not found: {input_glb}")
    if not worker_file.exists() and not worker_file.is_absolute():
        repo_candidate = Path(__file__).resolve().parents[2] / worker_file
        if repo_candidate.exists():
            worker_file = repo_candidate
    if not worker_file.exists():
        raise typer.BadParameter(f"Skin cleanup worker not found: {worker_file}")

    input_dir.mkdir(parents=True, exist_ok=True)
    staged_dir = input_dir / "skin_cleanup"
    scripts_dir = input_dir / "scripts"
    staged_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    staged_glb = staged_dir / input_glb.name
    staged_worker = scripts_dir / "anatomical_cleanup_worker.py"
    helper_file = worker_file.parent / "anatomical_skinning.py"
    staged_helper = scripts_dir / "anatomical_skinning.py"
    shutil.copy2(input_glb, staged_glb)
    shutil.copy2(worker_file, staged_worker)
    if helper_file.exists():
        shutil.copy2(helper_file, staged_helper)

    try:
        output_base = _cleanup_output_base_name(
            output_name,
            default=f"{input_glb.stem}_headfix",
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    output_host = out_dir / f"{output_base}.glb"
    summary_host = out_dir / f"{output_base}.skin_cleanup.json"
    existing_outputs = [path for path in (output_host, summary_host) if path.exists()]
    if existing_outputs:
        raise typer.BadParameter(
            "Refusing to overwrite existing cleanup output(s): "
            + ", ".join(str(path) for path in existing_outputs)
        )
    staged_worker_container = f"/app/comfy/input/scripts/{staged_worker.name}"
    worker_container = "/app/comfy/custom_nodes/ComfyUI-UniRig/nodes/anatomical_cleanup_worker.py"
    input_container = f"/app/comfy/input/skin_cleanup/{staged_glb.name}"
    # remesher-comfy3d maps host workspace/output/comfyui to /app/comfy/output.
    # If the requested out_dir is /workspace/output/rigged, it is not directly mounted.
    # Write via /app/comfy/output/skin_cleanup, then copy back through the Jupyter-visible host path.
    output_container = f"/app/comfy/output/skin_cleanup/{output_host.name}"
    summary_container = f"/app/comfy/output/skin_cleanup/{summary_host.name}"

    container_stale_outputs = [
        output_container,
        summary_container,
        f"/app/comfy/output/comfyui/skin_cleanup/{output_host.name}",
        f"/app/comfy/output/comfyui/skin_cleanup/{summary_host.name}",
    ]
    clear = subprocess.run(
        ["docker", "exec", container, "rm", "-f", "--", *container_stale_outputs],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if clear.returncode != 0:
        if clear.stderr:
            typer.echo(clear.stderr.rstrip(), err=True)
        raise typer.Exit(clear.returncode)
    _clear_worker_output_candidates(
        input_dir=input_dir,
        subfolder="skin_cleanup",
        filenames=(output_host.name, summary_host.name),
    )

    staged_helper_container = f"/app/comfy/input/scripts/{staged_helper.name}"
    helper_container = "/app/comfy/custom_nodes/ComfyUI-UniRig/nodes/anatomical_skinning.py"
    stage_command = ["docker", "exec", container, "bash", "-lc", f"mkdir -p /app/comfy/output/skin_cleanup && cp {staged_worker_container} {worker_container} && if [ -f {staged_helper_container} ]; then cp {staged_helper_container} {helper_container}; fi"]
    stage = subprocess.run(stage_command, capture_output=True, text=True, timeout=60)
    if stage.returncode != 0:
        if stage.stderr:
            typer.echo(stage.stderr.rstrip(), err=True)
        raise typer.Exit(stage.returncode)

    command = [
        *_docker_bpy_exec_prefix(container),
        "python3", worker_container,
        input_container,
        output_container,
        "--mode", mode,
        "--repair-zones", repair_zones,
        "--max-fraction-per-zone", str(max_fraction_per_zone),
        "--summary-json", summary_container,
    ]
    if not validate:
        command.append("--no-validate")
    typer.echo("Running anatomical skin cleanup worker:")
    typer.echo(" ".join(command))
    process = subprocess.run(command, capture_output=True, text=True, timeout=1200)
    if process.stdout:
        typer.echo(process.stdout.rstrip())
    if process.returncode != 0:
        if process.stderr:
            typer.echo(process.stderr.rstrip(), err=True)
        raise typer.Exit(process.returncode)

    # Copy worker outputs from either the notebook or direct Docker host layout.
    recovered_glb = _recover_worker_output(
        input_dir=input_dir,
        subfolder="skin_cleanup",
        filename=output_host.name,
        destination=output_host,
    )
    recovered_summary = _recover_worker_output(
        input_dir=input_dir,
        subfolder="skin_cleanup",
        filename=summary_host.name,
        destination=summary_host,
    )
    if recovered_glb is None or not output_host.exists():
        raise typer.BadParameter(f"Skin cleanup completed but output was not found: {output_host}")
    if recovered_summary is None or not summary_host.exists():
        raise typer.BadParameter(f"Skin cleanup completed but summary was not found: {summary_host}")
    typer.echo(f"Cleaned GLB: {output_host}")
    typer.echo(f"Cleanup summary: {summary_host}")


@app.command("retarget-glb")
def retarget_glb(
    rigged_glb: Path = typer.Option(..., "--rigged-glb", "--mesh", help="Rigged GLB to animate."),
    animation_fbx: Path = typer.Option(..., "--animation", help="Mixamo FBX animation to retarget."),
    glb_name: str | None = typer.Option(None, "--glb-name", help="Output GLB base name."),
    worker_file: Path = typer.Option(DEFAULT_RETARGET_WORKER, help="ARP retarget worker script to stage into the Comfy3D container."),
    container: str = typer.Option("remesher-comfy3d", help="Docker container with bpy + Auto-Rig Pro/UniRig installed."),
    input_dir: Path = typer.Option(Path("workspace/input"), help="Host/Jupyter input directory mounted to /app/comfy/input."),
    out_dir: Path = typer.Option(Path("workspace/output/comfyui/animated"), help="Host/Jupyter directory where animated GLBs should be visible."),
    frame_start: int | None = typer.Option(None, help="Optional animation start frame."),
    frame_end: int | None = typer.Option(None, help="Optional animation end frame; <=0 uses source end."),
    validate: bool = typer.Option(True, help="Re-import exported GLB and validate animation deltas."),
) -> None:
    """Retarget a Mixamo FBX animation onto a rigged GLB using Auto-Rig Pro in Comfy3D."""
    import shutil
    import subprocess

    if not rigged_glb.exists():
        raise typer.BadParameter(f"Rigged GLB not found: {rigged_glb}")
    if not animation_fbx.exists():
        raise typer.BadParameter(f"Animation FBX not found: {animation_fbx}")
    if not worker_file.exists() and not worker_file.is_absolute():
        repo_candidate = Path(__file__).resolve().parents[2] / worker_file
        if repo_candidate.exists():
            worker_file = repo_candidate
    if not worker_file.exists():
        raise typer.BadParameter(f"Retarget worker not found: {worker_file}")

    input_dir.mkdir(parents=True, exist_ok=True)
    staged_dir = input_dir / "retarget"
    scripts_dir = input_dir / "scripts"
    staged_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    staged_glb = staged_dir / rigged_glb.name
    staged_anim = staged_dir / animation_fbx.name
    staged_worker = scripts_dir / "arp_retarget_worker.py"
    shutil.copy2(rigged_glb, staged_glb)
    shutil.copy2(animation_fbx, staged_anim)
    shutil.copy2(worker_file, staged_worker)

    output_base = glb_name or f"{rigged_glb.stem}_{animation_fbx.stem}_animated"
    if output_base.lower().endswith(".glb"):
        output_base = output_base[:-4]
    output_host = out_dir / f"{output_base}.glb"
    summary_host = out_dir / f"{output_base}.retarget.json"

    # These host/Jupyter paths are bind-mounted into remesher-comfy3d as /app/comfy/input and /app/comfy/output.
    staged_worker_container = f"/app/comfy/input/scripts/{staged_worker.name}"
    # The worker expects to live in ComfyUI-UniRig/nodes so its _repo_root() can
    # resolve bundled third_party/auto_rig_pro for bpy.ops.preferences.addon_enable.
    worker_container = "/app/comfy/custom_nodes/ComfyUI-UniRig/nodes/arp_retarget_worker.py"
    glb_container = f"/app/comfy/input/retarget/{staged_glb.name}"
    anim_container = f"/app/comfy/input/retarget/{staged_anim.name}"
    output_container = f"/app/comfy/output/animated/{output_host.name}"
    summary_container = f"/app/comfy/output/animated/{summary_host.name}"

    stage_command = [
        "docker", "exec", container,
        "bash", "-lc",
        f"cp {staged_worker_container} {worker_container}",
    ]
    stage = subprocess.run(stage_command, capture_output=True, text=True, timeout=60)
    if stage.returncode != 0:
        if stage.stderr:
            typer.echo(stage.stderr.rstrip(), err=True)
        raise typer.Exit(stage.returncode)

    command = [
        *_docker_bpy_exec_prefix(container),
        "python3", worker_container,
        glb_container,
        anim_container,
        output_container,
        "--summary-json", summary_container,
    ]
    if frame_start is not None:
        command.extend(["--frame-start", str(frame_start)])
    if frame_end is not None:
        command.extend(["--frame-end", str(frame_end)])
    if not validate:
        command.append("--no-validate")

    typer.echo("Running ARP retarget worker:")
    typer.echo(" ".join(command))
    process = subprocess.run(command, capture_output=True, text=True, timeout=1200)
    if process.stdout:
        typer.echo(process.stdout.rstrip())
    if process.returncode != 0:
        if process.stderr:
            typer.echo(process.stderr.rstrip(), err=True)
        raise typer.Exit(process.returncode)
    if not output_host.exists():
        raise typer.BadParameter(f"Retarget worker completed but output was not found: {output_host}")
    if not summary_host.exists():
        summary_host.write_text(json.dumps({"output_glb": str(output_host), "worker_stdout": process.stdout}, indent=2))
    typer.echo(f"Animated GLB: {output_host}")
    typer.echo(f"Retarget summary: {summary_host}")


@app.command("glb-to-usdz")
def glb_to_usdz(
    glb: Path = typer.Option(..., "--glb", "--input-glb", help="GLB to convert to USDZ."),
    output_name: str | None = typer.Option(None, "--output-name", help="Output USDZ file/base name."),
    out_dir: Path = typer.Option(Path("workspace/output/comfyui/usdz"), help="Directory for USDZ and summary JSON."),
    worker_file: Path = typer.Option(DEFAULT_USDZ_WORKER, help="Isolated GLB-to-USDZ bpy worker script."),
    bpy_container: str = typer.Option("remesher-comfy3d", help="Docker container to use when local Python cannot import bpy."),
    validate: bool = typer.Option(True, help="Re-import exported USDZ and validate structure."),
    disable_bone_shape: bool = typer.Option(True, help="Disable Blender glTF custom bone-shape helpers on source import."),
    export_animation: bool = typer.Option(True, help="Export animation data when present."),
) -> None:
    """Convert a GLB to USDZ with an isolated Blender/bpy worker."""
    if not glb.exists() or not glb.is_file():
        raise typer.BadParameter(f"Input GLB not found: {glb}")
    if not worker_file.exists() and not worker_file.is_absolute():
        repo_candidate = Path(__file__).resolve().parents[2] / worker_file
        if repo_candidate.exists():
            worker_file = repo_candidate
    if not worker_file.exists() or not worker_file.is_file():
        raise typer.BadParameter(f"USDZ worker not found: {worker_file}")

    out_dir.mkdir(parents=True, exist_ok=True)
    output_base = output_name or f"{glb.stem}.usdz"
    if not output_base.lower().endswith(".usdz"):
        output_base = f"{output_base}.usdz"
    output_usdz = out_dir / Path(output_base).name
    summary_json = out_dir / f"{output_usdz.name}.json"

    extra_args: list[str] = []
    if not validate:
        extra_args.append("--no-validate")
    if not disable_bone_shape:
        extra_args.append("--keep-bone-shapes")
    if not export_animation:
        extra_args.append("--no-animation")

    _run_bpy_worker(
        worker_file=worker_file,
        positional_inputs=[glb],
        positional_outputs=[output_usdz],
        extra_args=extra_args,
        summary_json=summary_json,
        bpy_container=bpy_container,
    )
    if not output_usdz.exists():
        raise typer.BadParameter(f"USDZ worker completed but did not create {output_usdz}")
    typer.echo(f"USDZ: {output_usdz}")
    typer.echo(f"Summary JSON: {summary_json}")


@app.command("pose-glb")
def pose_glb_command(
    rigged_glb: Path = typer.Option(..., "--rigged-glb", "--input-glb", help="Rigged/skinned GLB to pose."),
    pose_json: Path = typer.Option(..., "--pose-json", help="JSON file with per-bone rotations."),
    output_name: str = typer.Option("posed", help="Output GLB basename without extension."),
    out_dir: Path = typer.Option(Path("workspace/output/comfyui/posed"), help="Directory for posed GLB and summary JSON."),
    worker_file: Path = typer.Option(DEFAULT_POSE_GLB_WORKER, help="Isolated pose bpy worker script."),
    bpy_container: str = typer.Option("remesher-comfy3d", help="Docker container to use when local Python cannot import bpy."),
    validate: bool = typer.Option(True, help="Re-import posed GLB and validate structure."),
    disable_bone_shape: bool = typer.Option(True, help="Disable Blender glTF custom bone-shape helpers on source/reimport."),
    export_animation: bool = typer.Option(False, help="Export existing animation data along with the edited rest pose."),
) -> None:
    """Apply a simple bone-rotation pose JSON to a rigged GLB."""
    if not rigged_glb.exists() or not rigged_glb.is_file():
        raise typer.BadParameter(f"Rigged GLB not found: {rigged_glb}")
    if not pose_json.exists() or not pose_json.is_file():
        raise typer.BadParameter(f"Pose JSON not found: {pose_json}")
    if not worker_file.exists() and not worker_file.is_absolute():
        repo_candidate = Path(__file__).resolve().parents[2] / worker_file
        if repo_candidate.exists():
            worker_file = repo_candidate
    if not worker_file.exists() or not worker_file.is_file():
        raise typer.BadParameter(f"Pose worker not found: {worker_file}")

    out_dir.mkdir(parents=True, exist_ok=True)
    output_base = output_name if output_name.lower().endswith(".glb") else f"{output_name}.glb"
    output_glb = out_dir / Path(output_base).name
    summary_json = out_dir / f"{output_glb.name}.json"

    extra_args: list[str] = []
    if not validate:
        extra_args.append("--no-validate")
    if not disable_bone_shape:
        extra_args.append("--keep-bone-shapes")
    if export_animation:
        extra_args.append("--export-animation")

    _run_bpy_worker(
        worker_file=worker_file,
        positional_inputs=[rigged_glb, pose_json],
        positional_outputs=[output_glb],
        extra_args=extra_args,
        summary_json=summary_json,
        bpy_container=bpy_container,
    )
    if not output_glb.exists():
        raise typer.BadParameter(f"Pose worker completed but did not create {output_glb}")
    typer.echo(f"Posed GLB: {output_glb}")
    typer.echo(f"Summary JSON: {summary_json}")


def main() -> None:
    app()
