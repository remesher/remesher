#!/usr/bin/env python3
"""Download/preflight the exact model assets used by the Remesher demo workflows.

Run this inside the Comfy3D/ComfyUI container. It downloads to /app/comfy/models,
which is where the workflow nodes resolve models via folder_paths.models_dir.
"""
import argparse
import os
from pathlib import Path
from huggingface_hub import hf_hub_download, snapshot_download

MODELS_DIR = Path(os.environ.get("COMFY_MODELS_DIR", "/app/comfy/models"))
def clean_hf_token(value):
    if not value:
        return None
    value = str(value).strip().strip('"').strip("'")
    # Avoid accidentally passing notebook output/traceback text as an HTTP header.
    if not value.startswith("hf_") or any(ord(ch) > 127 for ch in value) or any(ch.isspace() for ch in value):
        print("⚠ Ignoring invalid HF token value. Paste only the raw token, e.g. hf_...")
        return None
    return value

HF_TOKEN = clean_hf_token(os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN"))

SINGLE_FILES = [
    # Qwen Image 2512 text-to-image workflow
    dict(group="qwenimage2512", repo_id="Comfy-Org/Qwen-Image_ComfyUI", subfolder="split_files/vae", filename="qwen_image_vae.safetensors", local_path="vae/qwen_image_vae.safetensors"),
    dict(group="qwenimage2512", repo_id="Comfy-Org/Qwen-Image_ComfyUI", subfolder="split_files/text_encoders", filename="qwen_2.5_vl_7b_fp8_scaled.safetensors", local_path="text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors"),
    dict(group="qwenimage2512", repo_id="Comfy-Org/Qwen-Image_ComfyUI", subfolder="split_files/diffusion_models", filename="qwen_image_2512_fp8_e4m3fn.safetensors", local_path="diffusion_models/qwen_image_2512_fp8_e4m3fn.safetensors"),
    dict(group="qwenimage2512", repo_id="lightx2v/Qwen-Image-Lightning", subfolder="", filename="Qwen-Image-Lightning-4steps-V1.0.safetensors", local_path="loras/Qwen-Image-Lightning-4steps-V1.0.safetensors"),

    # Qwen Image Edit 2511 workflow
    dict(group="qwenimageedit2511", repo_id="Comfy-Org/Qwen-Image-Edit_ComfyUI", subfolder="split_files/diffusion_models", filename="qwen_image_edit_2511_fp8mixed.safetensors", local_path="diffusion_models/qwen_image_edit_2511_fp8mixed.safetensors"),
    dict(group="qwenimageedit2511", repo_id="lightx2v/Qwen-Image-Edit-2511-Lightning", subfolder="", filename="Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors", local_path="loras/Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors"),

    # Trellis2 auxiliary sparse-structure decoder expected by ComfyUI-Trellis2.
    dict(group="trellis2", repo_id="microsoft/TRELLIS-image-large", subfolder="ckpts", filename="ss_dec_conv3d_16l8_fp16.json", local_path="microsoft/TRELLIS-image-large/ckpts/ss_dec_conv3d_16l8_fp16.json"),
    dict(group="trellis2", repo_id="microsoft/TRELLIS-image-large", subfolder="ckpts", filename="ss_dec_conv3d_16l8_fp16.safetensors", local_path="microsoft/TRELLIS-image-large/ckpts/ss_dec_conv3d_16l8_fp16.safetensors"),

    # Make-It-Animatable / MIA rigging files expected at /app/comfy/models/mia/*.pth.
    dict(group="mia", repo_id="jasongzy/Make-It-Animatable", subfolder="output/best/new", filename="bw.pth", local_path="mia/bw.pth"),
    dict(group="mia", repo_id="jasongzy/Make-It-Animatable", subfolder="output/best/new", filename="bw_normal.pth", local_path="mia/bw_normal.pth"),
    dict(group="mia", repo_id="jasongzy/Make-It-Animatable", subfolder="output/best/new", filename="joints.pth", local_path="mia/joints.pth"),
    dict(group="mia", repo_id="jasongzy/Make-It-Animatable", subfolder="output/best/new", filename="joints_coarse.pth", local_path="mia/joints_coarse.pth"),
    dict(group="mia", repo_id="jasongzy/Make-It-Animatable", subfolder="output/best/new", filename="pose.pth", local_path="mia/pose.pth"),
]

SNAPSHOTS = [
    # ComfyUI-Trellis2 loads microsoft/TRELLIS.2-4B from models/microsoft/TRELLIS.2-4B.
    dict(group="trellis2", repo_id="microsoft/TRELLIS.2-4B", local_path="microsoft/TRELLIS.2-4B"),
    # It also hard-fails unless this folder contains model.safetensors.
    dict(group="dinov3", repo_id="facebook/dinov3-vitl16-pretrain-lvd1689m", local_path="facebook/dinov3-vitl16-pretrain-lvd1689m"),
]

EXPECTED = [m["local_path"] for m in SINGLE_FILES] + [
    "microsoft/TRELLIS.2-4B/pipeline.json",
    "facebook/dinov3-vitl16-pretrain-lvd1689m/model.safetensors",
    "facebook/dinov3-vitl16-pretrain-lvd1689m/config.json",
    "facebook/dinov3-vitl16-pretrain-lvd1689m/preprocessor_config.json",
]


def selected(groups):
    if not groups or "all" in groups:
        return lambda item: True
    return lambda item: item["group"] in groups


def ensure_file(item, dry_run=False):
    target = MODELS_DIR / item["local_path"]
    if target.exists() and target.stat().st_size > 0:
        print(f"✓ {item['group']}: {target} ({target.stat().st_size:,} bytes)")
        return
    print(f"↓ {item['group']}: {item['repo_id']}/{item.get('subfolder','')}/{item['filename']} -> {target}")
    if dry_run:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    hf_hub_download(
        repo_id=item["repo_id"],
        subfolder=item.get("subfolder") or None,
        filename=item["filename"],
        local_dir=str(target.parent),
        token=HF_TOKEN,
    )
    downloaded = target.parent / item.get("subfolder", "") / item["filename"]
    if downloaded != target and downloaded.exists():
        downloaded.rename(target)
        # Best effort cleanup of now-empty subfolder chain under target.parent.
        try:
            downloaded.parent.rmdir()
        except OSError:
            pass
    if not target.exists() or target.stat().st_size == 0:
        raise RuntimeError(f"download did not create non-empty file: {target}")
    print(f"✓ downloaded {target} ({target.stat().st_size:,} bytes)")


def ensure_snapshot(item, dry_run=False):
    target = MODELS_DIR / item["local_path"]
    sentinel = target / ("model.safetensors" if item["group"] == "dinov3" else "pipeline.json")
    if sentinel.exists() and sentinel.stat().st_size > 0:
        print(f"✓ {item['group']}: {target} ({sentinel.name} present)")
        return
    print(f"↓ {item['group']}: snapshot {item['repo_id']} -> {target}")
    if dry_run:
        return
    target.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=item["repo_id"],
        local_dir=str(target),
        token=HF_TOKEN,
    )
    if not sentinel.exists() or sentinel.stat().st_size == 0:
        raise RuntimeError(f"snapshot missing sentinel: {sentinel}")
    print(f"✓ downloaded snapshot {target}")


def preflight():
    missing=[]
    for rel in EXPECTED:
        p = MODELS_DIR / rel
        if not p.exists() or (p.is_file() and p.stat().st_size == 0):
            missing.append(str(p))
        else:
            print(f"✓ present: {p}")
    if missing:
        print("\nMissing required model assets:")
        for p in missing:
            print(f"✗ {p}")
        return 1
    print("\nAll Remesher workflow model assets are present.")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--groups", default="all", help="Comma-separated groups: all,qwenimage2512,qwenimageedit2511,trellis2,dinov3,mia")
    ap.add_argument("--preflight", action="store_true", help="Only check required files; do not download")
    ap.add_argument("--dry-run", action="store_true", help="Print what would be downloaded")
    args = ap.parse_args()
    groups = {g.strip() for g in args.groups.split(",") if g.strip()}

    if args.preflight:
        raise SystemExit(preflight())

    pred = selected(groups)
    for item in SINGLE_FILES:
        if pred(item):
            ensure_file(item, dry_run=args.dry_run)
    for item in SNAPSHOTS:
        if pred(item):
            ensure_snapshot(item, dry_run=args.dry_run)

    print("\nFinal preflight:")
    raise SystemExit(preflight())

if __name__ == "__main__":
    main()
