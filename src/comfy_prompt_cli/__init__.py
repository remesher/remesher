from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
import typer
from pydantic import BaseModel, HttpUrl, ValidationError

app = typer.Typer(help="Send prompts to a ComfyUI server.")
CONFIG_PATH = Path("config.json")


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


def _find_node_by_class(prompt: dict[str, Any], class_type: str) -> tuple[str, dict[str, Any]] | None:
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
            if not isinstance(node, dict) or node.get("class_type") != "CLIPTextEncode":
                continue
            meta = node.get("_meta", {}) if isinstance(node.get("_meta"), dict) else {}
            title = str(meta.get("title", "")).lower()
            inputs = node.get("inputs", {}) if isinstance(node.get("inputs"), dict) else {}
            if "positive" in title or ("text" in inputs and str(inputs.get("text", "")).strip()):
                inputs["text"] = positive_prompt
                updated += 1
                changes.append(f"prompt -> node {node_id}")
        if updated == 0:
            raise typer.BadParameter("Could not find a positive CLIPTextEncode node to override prompt text.")

    if mesh_seed is not None:
        found = _find_node_by_class(prompt, "Trellis2MeshWithVoxelAdvancedGenerator")
        if not found or not _set_input_if_node(found[1], "seed", mesh_seed):
            raise typer.BadParameter("Could not find Trellis2MeshWithVoxelAdvancedGenerator for mesh_seed override.")
        changes.append(f"mesh_seed={mesh_seed} -> node {found[0]}")

    if target_face_num is not None:
        found = _find_node_by_class(prompt, "Trellis2SimplifyMesh")
        if not found or not _set_input_if_node(found[1], "target_face_num", target_face_num):
            raise typer.BadParameter("Could not find Trellis2SimplifyMesh for target_face_num override.")
        changes.append(f"target_face_num={target_face_num} -> node {found[0]}")

    if filename_prefix is not None:
        found = _find_node_by_class(prompt, "Trellis2ExportMesh")
        if not found or not _set_input_if_node(found[1], "filename_prefix", filename_prefix):
            raise typer.BadParameter("Could not find Trellis2ExportMesh for filename_prefix override.")
        changes.append(f"filename_prefix={filename_prefix} -> node {found[0]}")

    if texture_seed is not None:
        found = _find_node_by_class(prompt, "Trellis2MeshTexturing")
        if not found or not _set_input_if_node(found[1], "seed", texture_seed):
            raise typer.BadParameter("Could not find Trellis2MeshTexturing for texture_seed override.")
        changes.append(f"texture_seed={texture_seed} -> node {found[0]}")

    return changes


@app.command("health")
def health(config: Path = typer.Option(CONFIG_PATH, help="Path to config.json")) -> None:
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
    prompt_file: Path = typer.Argument(..., exists=True, readable=True, help="Path to prompt/workflow JSON"),
    config: Path = typer.Option(CONFIG_PATH, help="Path to config.json"),
    client_id: str | None = typer.Option(None, help="Optional ComfyUI client_id"),
    positive_prompt: str | None = typer.Option(None, "--prompt", help="Override positive prompt text"),
    mesh_seed: int | None = typer.Option(None, help="Override Trellis mesh seed"),
    target_face_num: int | None = typer.Option(None, help="Override target face count"),
    filename_prefix: str | None = typer.Option(None, help="Override output filename prefix"),
    texture_seed: int | None = typer.Option(None, help="Override Trellis texture seed"),
    dry_run: bool = typer.Option(False, help="Build payload but do not POST"),
) -> None:
    """Submit a prompt JSON file to ComfyUI /prompt."""
    cfg = _load_config(config)
    base = str(cfg.server_url).rstrip("/")

    try:
        data = json.loads(prompt_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"Invalid JSON in {prompt_file}: {exc}") from exc

    if not isinstance(data, dict):
        raise typer.BadParameter("Prompt JSON root must be an object.")

    prompt = _extract_prompt_payload(data)
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


def _get_history_item(client: httpx.Client, base: str, prompt_id: str) -> dict[str, Any] | None:
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
    refs: list[str] = []
    outputs = history_item.get("outputs", {})
    if not isinstance(outputs, dict):
        return refs

    for node_data in outputs.values():
        if not isinstance(node_data, dict):
            continue
        for value in node_data.values():
            if isinstance(value, str) and value.lower().endswith(".glb"):
                refs.append(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item.lower().endswith(".glb"):
                        refs.append(item)
    return refs


def _download_glb(client: httpx.Client, base: str, glb_ref: str, out_path: Path) -> None:
    if glb_ref.startswith("http://") or glb_ref.startswith("https://"):
        resp = client.get(glb_ref)
        resp.raise_for_status()
        out_path.write_bytes(resp.content)
        return

    # Try ComfyUI /view endpoint with output type.
    ref_path = Path(glb_ref)
    params: dict[str, str] = {"filename": ref_path.name, "type": "output"}
    if ref_path.parent.as_posix() not in ("", "."):
        params["subfolder"] = ref_path.parent.as_posix()

    query = urlencode(params)
    view_url = f"{base}/view?{query}"
    resp = client.get(view_url)
    resp.raise_for_status()
    out_path.write_bytes(resp.content)


@app.command("wait")
def wait_prompt(
    prompt_id: str = typer.Argument(..., help="ComfyUI prompt_id"),
    config: Path = typer.Option(CONFIG_PATH, help="Path to config.json"),
    poll_interval: float = typer.Option(2.0, min=0.5, help="Polling interval seconds"),
    timeout: float = typer.Option(1800.0, min=1.0, help="Max wait time in seconds"),
    download_glb: bool = typer.Option(True, help="Download generated GLB when available"),
    out_dir: Path = typer.Option(Path("downloads"), help="Directory to write downloaded files"),
) -> None:
    """Poll queue/history until prompt completes; optionally download GLB output."""
    cfg = _load_config(config)
    base = str(cfg.server_url).rstrip("/")

    async def _run_wait() -> None:
        elapsed = 0.0
        async with httpx.AsyncClient(timeout=60.0) as aclient:
            while elapsed <= timeout:
                # Queue status is useful for async progress visibility.
                q = await aclient.get(f"{base}/queue")
                q.raise_for_status()
                queue_state = q.json()

                h = await aclient.get(f"{base}/history/{prompt_id}")
                h.raise_for_status()
                history_payload = h.json()

                history_item: dict[str, Any] | None = None
                if isinstance(history_payload, dict):
                    if prompt_id in history_payload and isinstance(history_payload[prompt_id], dict):
                        history_item = history_payload[prompt_id]
                    elif "outputs" in history_payload:
                        history_item = history_payload

                if history_item is not None:
                    typer.echo("Prompt completed.")
                    typer.echo(json.dumps({"prompt_id": prompt_id, "queue": queue_state}, indent=2))

                    if download_glb:
                        glb_refs = _extract_glb_refs(history_item)
                        if not glb_refs:
                            typer.echo("No GLB reference found in history outputs.")
                            return

                        out_dir.mkdir(parents=True, exist_ok=True)
                        with httpx.Client(timeout=120.0) as client:
                            for ref in glb_refs:
                                filename = Path(ref).name or f"{prompt_id}.glb"
                                dest = out_dir / filename
                                _download_glb(client, base, ref, dest)
                                typer.echo(f"Downloaded {dest}")
                    return

                running = queue_state.get("queue_running", []) if isinstance(queue_state, dict) else []
                pending = queue_state.get("queue_pending", []) if isinstance(queue_state, dict) else []
                typer.echo(f"Waiting... running={len(running)} pending={len(pending)} elapsed={int(elapsed)}s")
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

        raise typer.BadParameter(f"Timed out waiting for prompt_id={prompt_id}")

    asyncio.run(_run_wait())


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
