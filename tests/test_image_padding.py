import json
from pathlib import Path

import pytest
from PIL import Image, ImageChops
from typer.testing import CliRunner

import comfy_prompt_cli as cli
from comfy_prompt_cli import app
from comfy_prompt_cli.image_padding import pad_image_on_canvas


def test_pad_image_centers_scaled_source_on_white_square_canvas(tmp_path):
    source = tmp_path / "source.png"
    output = tmp_path / "padded.png"
    Image.new("RGB", (100, 80), "black").save(source)

    result = pad_image_on_canvas(
        source,
        output,
        subject_scale=0.60,
        canvas_size=100,
    )

    assert result == output
    with Image.open(output).convert("RGB") as padded:
        assert padded.size == (100, 100)
        difference = ImageChops.difference(padded, Image.new("RGB", padded.size, "white"))
        assert difference.getbbox() == (20, 26, 80, 74)
        assert padded.getpixel((0, 0)) == (255, 255, 255)
        assert padded.getpixel((50, 50)) == (0, 0, 0)


@pytest.mark.parametrize("subject_scale", [0.0, -0.1, 1.01])
def test_pad_image_rejects_invalid_subject_scale(tmp_path, subject_scale):
    source = tmp_path / "source.png"
    Image.new("RGB", (10, 10), "black").save(source)

    with pytest.raises(ValueError, match="subject_scale"):
        pad_image_on_canvas(
            source,
            tmp_path / "padded.png",
            subject_scale=subject_scale,
            canvas_size=100,
        )


def test_pad_tpose_image_command_writes_requested_output(tmp_path):
    source = tmp_path / "source.png"
    output = tmp_path / "padded.png"
    Image.new("RGB", (100, 80), "black").save(source)

    result = CliRunner().invoke(
        app,
        [
            "pad-tpose-image",
            "--image",
            str(source),
            "--output",
            str(output),
            "--subject-scale",
            "0.6",
            "--canvas-size",
            "100",
        ],
    )

    assert result.exit_code == 0
    assert output.exists()
    assert str(output) in result.output


def test_pad_tpose_image_command_defaults_to_point_65_scale(tmp_path):
    source = tmp_path / "source.png"
    output = tmp_path / "padded.png"
    Image.new("RGB", (100, 80), "black").save(source)

    result = CliRunner().invoke(
        app,
        [
            "pad-tpose-image",
            "--image",
            str(source),
            "--output",
            str(output),
            "--canvas-size",
            "100",
        ],
    )

    assert result.exit_code == 0
    with Image.open(output).convert("RGB") as padded:
        difference = ImageChops.difference(padded, Image.new("RGB", padded.size, "white"))
        assert difference.getbbox() == (17, 24, 82, 76)


def test_pad_image_accepts_rgba_background_color(tmp_path):
    source = tmp_path / "transparent.png"
    output = tmp_path / "padded.png"
    Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(source)

    pad_image_on_canvas(
        source,
        output,
        subject_scale=0.5,
        canvas_size=20,
        background="#11223380",
    )

    with Image.open(output).convert("RGB") as padded:
        assert padded.getpixel((0, 0)) == (17, 34, 51)


def test_pad_image_applies_exif_orientation_before_resizing(tmp_path):
    source = tmp_path / "rotated.jpg"
    output = tmp_path / "padded.png"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (40, 20), "black").save(source, exif=exif)

    pad_image_on_canvas(
        source,
        output,
        subject_scale=0.6,
        canvas_size=100,
    )

    with Image.open(output).convert("RGB") as padded:
        difference = ImageChops.difference(padded, Image.new("RGB", padded.size, "white"))
        assert difference.getbbox() == (35, 20, 65, 80)


def test_image_to_glb_subject_scale_uploads_padded_image(tmp_path, monkeypatch):
    source = tmp_path / "source.png"
    Image.new("RGB", (100, 80), "black").save(source)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"server_url": "http://127.0.0.1:8188/"}))
    uploaded = {}

    def fake_upload(base, image_path, overwrite=True):
        uploaded["path"] = image_path
        return image_path.name

    monkeypatch.setattr(cli, "_upload_input_image", fake_upload)
    monkeypatch.setattr(
        cli,
        "_submit_wait_and_download",
        lambda **kwargs: [tmp_path / "mesh.glb"],
    )

    result = CliRunner().invoke(
        app,
        [
            "image-to-glb",
            "--image",
            str(source),
            "--workflow-file",
            str(Path(__file__).resolve().parents[1] / "examples" / "img_to_trellis2.json"),
            "--config",
            str(config),
            "--subject-scale",
            "0.6",
            "--padding-canvas-size",
            "100",
            "--out-dir",
            str(tmp_path / "downloads"),
        ],
    )

    assert result.exit_code == 0
    padded = uploaded["path"]
    assert padded != source
    assert padded.exists()
    with Image.open(padded).convert("RGB") as image:
        difference = ImageChops.difference(image, Image.new("RGB", image.size, "white"))
        assert difference.getbbox() == (20, 26, 80, 74)
    assert "Padded input image" in result.output


def test_image_to_glb_default_uploads_original_image(tmp_path, monkeypatch):
    source = tmp_path / "source.png"
    Image.new("RGB", (100, 80), "black").save(source)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"server_url": "http://127.0.0.1:8188/"}))
    uploaded = {}

    def fake_upload(base, image_path, overwrite=True):
        uploaded["path"] = image_path
        return image_path.name

    monkeypatch.setattr(cli, "_upload_input_image", fake_upload)
    monkeypatch.setattr(
        cli,
        "_submit_wait_and_download",
        lambda **kwargs: [tmp_path / "mesh.glb"],
    )

    result = CliRunner().invoke(
        app,
        [
            "image-to-glb",
            "--image",
            str(source),
            "--workflow-file",
            str(Path(__file__).resolve().parents[1] / "examples" / "img_to_trellis2.json"),
            "--config",
            str(config),
            "--out-dir",
            str(tmp_path / "downloads"),
        ],
    )

    assert result.exit_code == 0
    assert uploaded["path"] == source
    assert "Padded input image" not in result.output
