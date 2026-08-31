"""Deterministic image framing helpers for T-pose-safe 3D inputs."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageColor, ImageOps


def pad_image_on_canvas(
    source: Path,
    destination: Path,
    *,
    subject_scale: float = 0.65,
    canvas_size: int = 1024,
    background: str = "white",
) -> Path:
    """Center an aspect-preserving source resize on a square background canvas."""
    if not 0.0 < subject_scale <= 1.0:
        raise ValueError("subject_scale must be greater than 0 and at most 1")
    if canvas_size <= 0:
        raise ValueError("canvas_size must be greater than 0")
    if destination.suffix.lower() != ".png":
        raise ValueError("destination must use a .png suffix")
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(source)

    max_subject_size = max(1, round(canvas_size * subject_scale))
    background_rgba = ImageColor.getcolor(background, "RGBA")

    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGBA")
        ratio = min(max_subject_size / image.width, max_subject_size / image.height)
        resized_size = (
            max(1, round(image.width * ratio)),
            max(1, round(image.height * ratio)),
        )
        resized = image.resize(resized_size, Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (canvas_size, canvas_size), background_rgba)
        offset = (
            (canvas_size - resized.width) // 2,
            (canvas_size - resized.height) // 2,
        )
        canvas.alpha_composite(resized, offset)

    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(destination, format="PNG", optimize=True)
    return destination
