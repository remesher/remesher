"""Native 512-resolution single-image TRELLIS.2/Pixal3D API workflow.

Derived from ComfyUI 7a28332047b6af638dc6c7f72ef3481a718769fd.
No custom nodes, editor widgets, preview dependencies or lazy switches.
Input should be a cropped, background-clean object image. This is not the
1536-resolution official editor preset, or a rigging/animation backend.
"""

from __future__ import annotations

import os
import struct
import tempfile
import time
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
    filename_prefix="remesher",
    camera_angle=49.13,
):
    if model not in {"trellis2", "pixal3d"}:
        raise ValueError("native model must be trellis2 or pixal3d")
    if not 1 <= target_face_num <= 50000000:
        raise ValueError("native target face count must be between 1 and 50000000")
    if not all(
        isinstance(seed, int) and 0 <= seed < 2**64
        for seed in (mesh_seed, texture_seed)
    ):
        raise ValueError("native seeds must be unsigned 64-bit integers")
    if not 1 <= camera_angle <= 170:
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

    def sample(key, model_link, positive, negative, latent, seed, steps, cfg):
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
            scheduler="normal",
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
    mesh = node("shape_decode", "VaeDecodeShapeTrellis", samples=shape, vae=shape_vae)
    node(
        "texture_stage",
        "Trellis2TextureStage",
        positive=["shape_stage", 0],
        negative=["shape_stage", 1],
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
    reduced = node(
        "decimate",
        "DecimateMesh",
        mesh=mesh,
        target_face_count=target_face_num,
        placement_mode="midpoint",
    )
    uv = node(
        "unwrap",
        "UnwrapMesh",
        mesh=reduced,
        segmenter="pec",
        resolution=1024,
        padding=1,
        weld_distance=0.0002,
    )
    node(
        "bake",
        "BakeTextureFromVoxel",
        mesh=uv,
        voxel_colors=colors,
        reference_mesh=mesh,
        texture_size=1024,
    )
    textured = node(
        "textured",
        "ApplyTextureToMesh",
        mesh=uv,
        base_color=["bake", 0],
        metallic=["bake", 1],
        roughness=["bake", 2],
    )
    node("save", "SaveGLB", mesh=textured, filename_prefix=filename_prefix)
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
        required = schema["input"].get("required", {})
        allowed = {**required, **schema["input"].get("optional", {})}
        inputs = node["inputs"]
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
                )
        time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
    raise TimeoutError(
        f"native prompt {prompt_id} timed out; operator-managed server job may still run (no global interrupt sent)"
    )


def _download(client, artifacts, out_dir):
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
                client.stream(
                    "GET",
                    "/view",
                    params={"filename": name, "subfolder": folder, "type": "output"},
                ) as response,
            ):
                response.raise_for_status()
                size = 0
                for chunk in response.iter_bytes():
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
