"""Native single-image TRELLIS.2/Pixal3D API workflow.

Derived from ComfyUI 7a28332047b6af638dc6c7f72ef3481a718769fd.
No custom nodes, editor widgets, preview dependencies or lazy switches.
Input should be a cropped, background-clean object image. This is not the
full official editor preset, or a rigging/animation backend. Shape defaults to
512; opt-in 1536 adds the official two-node shape cascade only.
"""

from __future__ import annotations

import math
import os
import socket
import struct
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from uuid import uuid4

import httpx


def build_prompt(
    image: str,
    *,
    model="trellis2",
    mesh_seed=42,
    texture_seed=43,
    target_face_num=80000,
    no_decimation=False,
    mesh_repair="none",
    repair_resolution=512,
    repair_max_perimeter=0.03,
    repair_drop_small_components=0.005,
    filename_prefix="remesher",
    camera_angle=None,
    shape_resolution=512,
    atlas_resolution=1024,
):
    if type(atlas_resolution) is not int or atlas_resolution not in {1024, 4096}:
        raise ValueError("native atlas resolution must be 1024 or 4096")
    if type(shape_resolution) is not int or shape_resolution not in {512, 1536}:
        raise ValueError("native shape resolution must be 512 or 1536")
    if model not in {"trellis2", "pixal3d"}:
        raise ValueError("native model must be trellis2 or pixal3d")
    if mesh_repair not in {"none", "fill", "solid"}:
        raise ValueError("mesh repair must be none, fill or solid")
    if mesh_repair != "none" and not no_decimation:
        raise ValueError("mesh repair requires --no-decimation (no hidden face cap)")
    if type(repair_resolution) is not int or not 32 <= repair_resolution <= 2048:
        raise ValueError("repair resolution must be an integer from 32 to 2048")
    for value, upper, name in (
        (repair_max_perimeter, 0.03, "repair max perimeter"),
        (repair_drop_small_components, 0.5, "repair drop small components"),
    ):
        if type(value) not in (int, float) or not 0 <= value <= upper:
            raise ValueError(f"{name} must be finite and between 0 and {upper}")
    if not 1 <= target_face_num <= 50000000:
        raise ValueError("native target face count must be between 1 and 50000000")
    if not all(
        isinstance(seed, int) and 0 <= seed < 2**64
        for seed in (mesh_seed, texture_seed)
    ):
        raise ValueError("native seeds must be unsigned 64-bit integers")
    if camera_angle is not None and not 1 <= camera_angle <= 170:
        raise ValueError("native camera angle must be between 1 and 170")
    _relative_path(filename_prefix)
    graph = {}

    def node(key, cls, **inputs):
        graph[key] = {"class_type": cls, "inputs": inputs}
        return [key, 0]

    image_ref = node("image", "LoadImage", image=image)
    vision = node(
        "vision", "CLIPVisionLoader", clip_name="dino_v3_L_naf_fp32.safetensors"
    )
    model_ref = node(
        "model",
        "UNETLoader",
        unet_name=("trellis_2" if model == "trellis2" else "pixal3d")
        + "_int8_convrot.safetensors",
        weight_dtype="default",
    )
    shape_vae = node(
        "shape_vae", "VAELoader", vae_name="trellis_2_shape_vae_bf16.safetensors"
    )
    texture_vae = node(
        "texture_vae", "VAELoader", vae_name="trellis_2_texture_vae_bf16.safetensors"
    )
    conditioning_inputs = {"clip_vision_model": vision, "image": image_ref}
    if model == "pixal3d":
        if camera_angle is None:
            moge = node("moge_model", "LoadMoGeModel",
                        model_name="moge_2_vitl_normal_fp16.safetensors")
            geometry = node("moge_inference", "MoGeInference", moge_model=moge,
                            image=image_ref, resolution_level=9, fov_x_degrees=0.0,
                            batch_size=4, force_projection=True, apply_mask=True,
                            refine_steps=3)
            camera_angle = node("moge_fov", "MoGeGeometryToFOV",
                                moge_geometry=geometry, axis="horizontal", unit="degrees")
        conditioning_inputs["camera_angle_x"] = camera_angle
    node(
        "conditioning",
        "Trellis2Conditioning" if model == "trellis2" else "Pixal3DConditioning",
        **conditioning_inputs,
    )
    empty = node("empty", "EmptyTrellis2LatentStructure", batch_size=1)
    structure_cfg = node(
        "structure_cfg",
        "CFGOverride",
        model=model_ref,
        cfg=1.0,
        start_percent=0.667,
        end_percent=1.0,
    )
    structure_rescale = node(
        "structure_rescale", "RescaleCFG", model=structure_cfg, multiplier=0.7
    )
    structure_model = node(
        "structure_model", "ModelSamplingSD3", model=structure_rescale, shift=5.0
    )

    def sample(key, model_link, positive, negative, latent, seed, steps, cfg, scheduler="normal"):
        return node(
            key,
            "KSampler",
            model=model_link,
            positive=positive,
            negative=negative,
            latent_image=latent,
            seed=seed,
            steps=steps,
            cfg=cfg,
            sampler_name="euler",
            scheduler=scheduler,
            denoise=1.0,
        )

    structure = sample(
        "structure_sample",
        structure_model,
        ["conditioning", 0],
        ["conditioning", 1],
        empty,
        mesh_seed,
        12,
        7.5,
    )
    voxel = node(
        "structure_decode",
        "VaeDecodeStructureTrellis2",
        samples=structure,
        vae=shape_vae,
        resolution="32",
    )
    node(
        "shape_stage",
        "Trellis2ShapeStage",
        positive=["conditioning", 0],
        negative=["conditioning", 1],
        voxel=voxel,
    )
    shape_cfg = node(
        "shape_cfg",
        "CFGOverride",
        model=model_ref,
        cfg=1.0,
        start_percent=0.769,
        end_percent=1.0,
    )
    shape_model = node("shape_model", "RescaleCFG", model=shape_cfg, multiplier=0.5)
    shape = sample(
        "shape_sample",
        shape_model,
        ["shape_stage", 0],
        ["shape_stage", 1],
        ["shape_stage", 2],
        mesh_seed,
        20,
        7.5,
    )
    shape_conditioning = "shape_stage"
    if shape_resolution == 1536:
        node("shape_upsample", "Trellis2UpsampleStage",
             positive=["shape_stage", 0], negative=["shape_stage", 1],
             shape_latent=shape, vae=shape_vae, target_resolution=1536)
        shape = sample("shape_refine", shape_model,
                       ["shape_upsample", 0], ["shape_upsample", 1],
                       ["shape_upsample", 2], mesh_seed, 12, 7.5, scheduler="simple")
        shape_conditioning = "shape_upsample"
    mesh = node("shape_decode", "VaeDecodeShapeTrellis", samples=shape, vae=shape_vae)
    node(
        "texture_stage",
        "Trellis2TextureStage",
        positive=[shape_conditioning, 0],
        negative=[shape_conditioning, 1],
        shape_latent=shape,
    )
    texture = sample(
        "texture_sample",
        model_ref,
        ["texture_stage", 0],
        ["texture_stage", 1],
        ["texture_stage", 2],
        texture_seed,
        12,
        1.0,
    )
    colors = node(
        "texture_decode",
        "VaeDecodeTextureTrellis",
        samples=texture,
        vae=texture_vae,
        shape_subdivides=["shape_decode", 1],
    )
    reduced = mesh if no_decimation else node(
        "decimate",
        "DecimateMesh",
        mesh=mesh,
        target_face_count=target_face_num,
        placement_mode="midpoint",
    )
    if mesh_repair == "solid":
        reduced = node(
            "repair_remesh", "RemeshMesh", mesh=reduced,
            resolution=repair_resolution, sign_mode="solid",
            **{"sign_mode.fill": 20.0, "sign_mode.qef": False},
            band=1.0, project_back=0.0, fix_poles=False, smooth_iters=0,
            drop_small_components=repair_drop_small_components,
            precluster_max_verts=0,
        )
    if mesh_repair != "none":
        reduced = node(
            "repair_fill", "FillHoles", mesh=reduced,
            max_perimeter=repair_max_perimeter,
            weld_epsilon_rel=0.0, max_vertices=16, fill_chains=False,
        )
        node("save_decoded", "SaveGLB", mesh=mesh,
             filename_prefix=filename_prefix + "_decoded")
        node("save_repaired", "SaveGLB", mesh=reduced,
             filename_prefix=filename_prefix + "_repaired")
    uv = node(
        "unwrap",
        "UnwrapMesh",
        mesh=reduced,
        segmenter="pec",
        resolution=atlas_resolution,
        padding=1,
        weld_distance=0.0002,
    )
    node(
        "bake",
        "BakeTextureFromVoxel",
        mesh=uv,
        voxel_colors=colors,
        reference_mesh=mesh,
        texture_size=atlas_resolution,
    )
    textured = node(
        "textured",
        "ApplyTextureToMesh",
        mesh=uv,
        base_color=["bake", 0],
        metallic=["bake", 1],
        roughness=["bake", 2],
    )
    # Attach normals on the final UV/material mesh, after all topology changes.
    # 180 degrees preserves indexed topology and smooths coincident UV seams.
    # The pinned SaveGLB serializer explicitly carries mesh.normals.
    smooth = node("smooth_normals", "MeshSmoothNormals", mesh=textured, crease_angle=180.0)
    node("save", "SaveGLB", mesh=smooth, filename_prefix=filename_prefix)
    return graph


def _relative_path(value, *, empty=False):
    if (
        not isinstance(value, str)
        or (not value and not empty)
        or "\\" in value
        or "\x00" in value
        or ":" in value
    ):
        raise ValueError("unsafe native artifact path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {".", ".."} for part in value.split("/")):
        raise ValueError("unsafe native artifact path")
    return value


def validate_prompt(graph, info):
    """Fail closed on missing nodes/keys, links, primitive types and model enums.

    The server's /prompt validator remains authoritative for dynamic inputs.
    """
    for node in graph.values():
        if node["class_type"] not in info:
            raise ValueError(f"native node unavailable: {node['class_type']}")
    for node in graph.values():
        cls = node["class_type"]
        schema = info[cls]
        required = dict(schema["input"].get("required", {}))
        allowed = {**required, **schema["input"].get("optional", {})}
        inputs = node["inputs"]
        # V3 DynamicCombo serializes children as dotted sibling inputs.
        pending = list(allowed.items())
        while pending:
            name, spec = pending.pop()
            if spec[0] != "COMFY_DYNAMICCOMBO_V3" or name not in inputs:
                continue
            selected = next((o for o in spec[1]["options"]
                             if o["key"] == inputs[name]), None)
            if selected is None:
                raise ValueError(f"native dynamic option unavailable: {cls}.{name}")
            for category in ("required", "optional"):
                for child, child_spec in selected["inputs"].get(category, {}).items():
                    key = f"{name}.{child}"
                    allowed[key] = child_spec
                    if category == "required":
                        required[key] = child_spec
                    pending.append((key, child_spec))
        if set(required) - inputs.keys() or inputs.keys() - allowed.keys():
            raise ValueError(f"native input schema mismatch: {cls}")
        for name, value in inputs.items():
            spec = allowed[name]
            kind = spec[0]
            # LoadImage's enum lists *existing* files; our upload is next.
            # The server validates the final uploaded reference at /prompt.
            if cls == "LoadImage" and name == "image" and isinstance(value, str):
                continue
            if isinstance(value, list):
                if (
                    len(value) != 2
                    or value[0] not in graph
                    or type(value[1]) is not int
                    or value[1] < 0
                ):
                    raise ValueError(f"native link invalid: {cls}.{name}")
                outputs = info[graph[value[0]]["class_type"]]["output"]
                if value[1] >= len(outputs) or (
                    isinstance(kind, str)
                    and outputs[value[1]] not in kind.split(",")
                    and kind != "*"
                ):
                    raise ValueError(f"native link type mismatch: {cls}.{name}")
            elif isinstance(kind, list) and value not in kind:
                raise ValueError(f"native model or option unavailable: {cls}.{name}")
            elif kind == "COMBO":
                if value not in spec[1].get("options", []):
                    raise ValueError(f"native model or option unavailable: {cls}.{name}")
            elif kind == "COMFY_DYNAMICCOMBO_V3":
                if value not in [option["key"] for option in spec[1]["options"]]:
                    raise ValueError(f"native dynamic option unavailable: {cls}.{name}")
            elif kind == "STRING" and not isinstance(value, str):
                raise ValueError(f"native string type mismatch: {cls}.{name}")
            elif kind == "BOOLEAN" and not isinstance(value, bool):
                raise ValueError(f"native boolean type mismatch: {cls}.{name}")
            elif kind in ("INT", "FLOAT"):
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or (kind == "INT" and not isinstance(value, int))
                    or not math.isfinite(value)
                ):
                    raise ValueError(f"native numeric type mismatch: {cls}.{name}")
                bounds = spec[1] if len(spec) > 1 else {}
                if value < bounds.get("min", float("-inf")) or value > bounds.get(
                    "max", float("inf")
                ):
                    raise ValueError(f"native numeric range mismatch: {cls}.{name}")


def _json(response):
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict):
        raise TypeError("native API returned non-object JSON")
    return result


def generate(
    client: httpx.Client,
    image: Path,
    out_dir: Path,
    *,
    timeout=1800,
    poll_interval=2,
    client_id=None,
    validate=True,
    **options,
):
    graph = build_prompt(image.name, **options)
    # Model/schema failures are read-only: don't upload or queue first.
    if validate:
        validate_prompt(graph, _json(client.get("/object_info")))
    with image.open("rb") as source:
        upload = _json(
            client.post(
                "/upload/image",
                files={"image": (f"remesher-{uuid4().hex}{image.suffix}", source)},
                data={"type": "input", "overwrite": "false"},
            )
        )
    name = _relative_path(upload["name"])
    folder = _relative_path(upload.get("subfolder", ""), empty=True)
    if upload.get("type", "input") != "input":
        raise ValueError("native upload did not return an input image")
    graph["image"]["inputs"]["image"] = f"{folder}/{name}" if folder else name
    submitted = _json(
        client.post(
            "/prompt", json={"prompt": graph, "client_id": client_id or str(uuid4())}
        )
    )
    prompt_id = submitted.get("prompt_id")
    if not isinstance(prompt_id, str) or not prompt_id or submitted.get("node_errors"):
        raise ValueError("native prompt rejected")
    _relative_path(prompt_id)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        history = _json(client.get(f"/history/{prompt_id}"))
        entry = history.get(prompt_id)
        if entry:
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError(
                    f"native execution failed for prompt {prompt_id}; inspect owned server log/history"
                )
            if status.get("completed"):
                return _download(
                    client,
                    entry.get("outputs", {}).get("save", {}).get("3d", []),
                    out_dir,
                    deadline=deadline,
                )
        time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
    raise TimeoutError(
        f"native prompt {prompt_id} timed out; operator-managed server job may still run (no global interrupt sent)"
    )


def _remaining(deadline):
    if deadline is None:
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("native artifact transfer timed out")
    return remaining


class _FreshArtifactConnection(Exception):
    """Retry only before any request bytes are sent on an idle HTTP/1 socket."""


@contextmanager
def _artifact_response(client, params, deadline):
    """Own an HTTP/1 socket before headers, through the final body read.

    HTTPX read timeouts measure inactivity, not total transfer duration. The
    httpcore trace extension exposes a newly connected stream before headers.
    An idle pooled connection has no connect event: reject it *before sending*
    so httpcore closes just that acquired HTTP/1 connection, then retry. Never
    close the caller's client/pool or a multiplexed HTTP/2 socket.
    """
    stream = None
    timer = None

    def trace(event, info):
        nonlocal stream, timer
        if event == "http11.send_request_headers.started" and stream is None:
            raise _FreshArtifactConnection()
        if event == "http11.response_closed.complete":
            if timer is not None:
                timer.cancel()
                timer.join()
                timer = None
            stream = None
        if event == "http2.send_request_headers.started":
            raise ValueError("native artifact deadlines require an HTTP/1 connection")
        if event in {
            "connection.connect_tcp.complete",
            "connection.connect_unix_socket.complete",
            "connection.start_tls.complete",
        }:
            stream = info["return_value"]
        if event.endswith(".started") and "response_closed" not in event:
            remaining = _remaining(deadline)
            # Pool acquisition may already have spent some of the budget.
            if "timeout" in info:
                info["timeout"] = remaining
        if event == "http11.send_request_headers.started" and stream is not None:
            sock = stream.get_extra_info("socket")
            if sock is None:
                raise ValueError("native artifact deadline requires a socket")

            def expire():
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass  # This response has already closed.

            remaining = _remaining(deadline)
            assert remaining is not None  # Trace is installed only with a deadline.
            timer = threading.Timer(remaining, expire)
            timer.daemon = True
            timer.start()

    try:
        while True:
            try:
                with client.stream(
                    "GET",
                    "/view",
                    params=params,
                    timeout=_remaining(deadline)
                    if deadline is not None
                    else client.timeout,
                    headers={"Connection": "close"},
                    extensions={"trace": trace} if deadline is not None else {},
                ) as response:
                    _remaining(deadline)
                    response.raise_for_status()
                    yield response
                    _remaining(deadline)
                break
            except _FreshArtifactConnection:
                # No request was sent. The rejected connection is now closed.
                _remaining(deadline)
    except httpx.HTTPError:
        _remaining(deadline)  # Normalize deadline-triggered socket errors.
        raise
    finally:
        if timer is not None:
            timer.cancel()
            timer.join()


def _download(client, artifacts, out_dir, *, deadline=None):
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("native completed without SaveGLB 3d artifacts")
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for artifact in artifacts:
        name = _relative_path(artifact["filename"])
        folder = _relative_path(artifact.get("subfolder", ""), empty=True)
        if (
            "/" in name
            or not name.lower().endswith(".glb")
            or artifact.get("type") != "output"
        ):
            raise ValueError("native SaveGLB returned an invalid artifact")
        # Never trust remote paths as local write targets or overwrite existing
        # files/symlinks. Retain server subfolder only in the /view query.
        fd, filename = tempfile.mkstemp(
            prefix="native-", suffix="-" + name, dir=out_dir
        )
        path = Path(filename)
        try:
            with (
                os.fdopen(fd, "wb") as output,
                _artifact_response(
                    client,
                    {"filename": name, "subfolder": folder, "type": "output"},
                    deadline,
                ) as response,
            ):
                size = 0
                for chunk in response.iter_bytes():
                    _remaining(deadline)
                    size += len(chunk)
                    if size > 512 * 1024 * 1024:
                        raise ValueError("native artifact exceeds 512 MiB limit")
                    output.write(chunk)
            with path.open("rb") as file:
                header = file.read(12)
            if len(header) != 12 or struct.unpack("<4sII", header) != (
                b"glTF",
                2,
                size,
            ):
                raise ValueError("native artifact is not a complete GLB v2")
            paths.append(path)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
    return paths
