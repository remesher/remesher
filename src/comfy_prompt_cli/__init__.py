from __future__ import annotations

import asyncio
import json
import mimetypes
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
import typer
from pydantic import BaseModel, HttpUrl, ValidationError

app = typer.Typer(help="Send prompts to a ComfyUI server.")
CONFIG_PATH = Path("config.json")
DEFAULT_TEXT_TO_IMAGE_WORKFLOW = Path("examples/qwen_image_2512.json")
DEFAULT_IMAGE_TEXT_TO_IMAGE_WORKFLOW = Path("examples/qwen_image_edit_2511.json")
DEFAULT_IMAGE_TO_GLB_WORKFLOW = Path("examples/img_to_trellis2.json")
DEFAULT_RIG_GLB_WORKFLOW = Path("examples/rig_glb_mia.json")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
GLB_EXTENSIONS = {".glb"}


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
        if not found or not _set_input_if_node(
            found[1], "filename_prefix", filename_prefix
        ):
            raise typer.BadParameter(
                "Could not find Trellis2ExportMesh for filename_prefix override."
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


def _upload_input_image(base: str, image_path: Path, overwrite: bool = True) -> str:
    if not image_path.exists():
        raise typer.BadParameter(f"Image file not found: {image_path}")

    guessed_type, _ = mimetypes.guess_type(str(image_path))
    content_type = guessed_type or "application/octet-stream"
    with image_path.open("rb") as f, httpx.Client(timeout=120.0) as client:
        files = {"image": (image_path.name, f, content_type)}
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

    raise typer.BadParameter(f"Unexpected upload response: {json.dumps(payload)}")


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


async def _wait_for_completion(
    base: str,
    prompt_id: str,
    poll_interval: float,
    timeout: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    elapsed = 0.0
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
                return (
                    queue_state if isinstance(queue_state, dict) else {}
                ), history_item

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


def _submit_wait_and_download(
    *,
    base: str,
    prompt: dict[str, Any],
    client_id: str | None,
    poll_interval: float,
    timeout: float,
    out_dir: Path,
    extensions: set[str],
) -> list[Path]:
    result = _submit_prompt(base, prompt, client_id)
    prompt_id = result.get("prompt_id")
    if not isinstance(prompt_id, str):
        raise typer.BadParameter(f"Unexpected /prompt response: {json.dumps(result)}")

    typer.echo(json.dumps(result, indent=2))
    queue_state, history_item = asyncio.run(
        _wait_for_completion(base, prompt_id, poll_interval, timeout)
    )
    typer.echo("Prompt completed.")
    typer.echo(json.dumps({"prompt_id": prompt_id, "queue": queue_state}, indent=2))
    return _download_from_history_by_ext(
        base, prompt_id, history_item, out_dir, extensions
    )


@app.command("wait")
def wait_prompt(
    prompt_id: str = typer.Argument(..., help="ComfyUI prompt_id"),
    config: Path = typer.Option(CONFIG_PATH, help="Path to config.json"),
    poll_interval: float = typer.Option(2.0, min=0.5, help="Polling interval seconds"),
    timeout: float = typer.Option(1800.0, min=1.0, help="Max wait time in seconds"),
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
        _wait_for_completion(base, prompt_id, poll_interval, timeout)
    )
    typer.echo("Prompt completed.")
    typer.echo(json.dumps({"prompt_id": prompt_id, "queue": queue_state}, indent=2))

    if download_glb:
        downloaded = _download_from_history(base, prompt_id, history_item, out_dir)
        if not downloaded:
            typer.echo("No GLB reference found in history outputs.")
            return
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
    )
    if not downloaded:
        typer.echo("No GLB reference found in history outputs.")
        return
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
    )
    if not downloaded:
        typer.echo("No image output reference found in history outputs.")
        return
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
    )
    if not downloaded:
        typer.echo("No image output reference found in history outputs.")
        return
    for path in downloaded:
        typer.echo(f"Downloaded {path}")


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
    target_face_num: int | None = typer.Option(None, help="Override target face count"),
    filename_prefix: str | None = typer.Option(
        None, help="Override output filename prefix"
    ),
    texture_seed: int | None = typer.Option(None, help="Override Trellis texture seed"),
    poll_interval: float = typer.Option(2.0, min=0.5, help="Polling interval seconds"),
    timeout: float = typer.Option(1800.0, min=1.0, help="Max wait time in seconds"),
    out_dir: Path = typer.Option(
        Path("downloads"), help="Directory to write downloaded files"
    ),
) -> None:
    """Convert image to GLB using img_to_trellis2 workflow."""
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
    )
    if not downloaded:
        typer.echo("No GLB reference found in history outputs.")
        return
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
    poll_interval: float = typer.Option(2.0, min=0.5, help="Polling interval seconds"),
    timeout: float = typer.Option(1800.0, min=1.0, help="Max wait time in seconds"),
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
        node_id = _set_input_on_first_node_by_class(
            prompt, "Hy3DUploadMesh", "mesh", mesh
        )
        if node_id is None:
            raise typer.BadParameter("Could not find Hy3DUploadMesh for mesh override.")
        changes.append(f"mesh={mesh} -> node {node_id}")

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
    )
    if not downloaded:
        typer.echo("No GLB reference found in history outputs.")
        return
    for path in downloaded:
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

    cfg = AppConfig(server_url=server_url)
    out.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(f"Wrote {out}")


def main() -> None:
    app()
