import json
import subprocess
import sys

from comfy_prompt_cli.native_setup import SetupConfig, plan


def test_pixal_plan_selects_only_pinned_branch_and_shared_assets(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "comfy_prompt_cli.native_setup",
            "plan",
            "--root",
            str(tmp_path / "runtime"),
            "--model",
            "pixal3d",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout
    report = json.loads(result.stdout)
    assert report["config"]["model"] == "pixal3d"
    paths = {m["path"] for m in report["models"]}
    assert "diffusion_models/pixal3d_int8_convrot.safetensors" in paths
    assert "geometry_estimation/moge_2_vitl_normal_fp16.safetensors" in paths
    assert "diffusion_models/trellis_2_int8_convrot.safetensors" not in paths
    assert len(paths) == 5
    trellis = plan(SetupConfig.at_root(tmp_path / "runtime"))
    shared = [
        m for m in trellis["models"] if not m["path"].startswith("diffusion_models/")
    ]
    assert all(m in report["models"] for m in shared)
    assert report["download_bytes"] == sum(m["size"] for m in report["models"])
    assert not (tmp_path / "runtime").exists()


def test_official_moge_download_is_allowed_and_verified(tmp_path):
    import hashlib

    import httpx

    from comfy_prompt_cli.native_download import download

    data = b"official repository allowlist fixture"
    model = {
        "repo": "Comfy-Org/MoGe",
        "revision": "a" * 40,
        "path": "geometry_estimation/test.safetensors",
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=data))
    ) as client:
        download(model, tmp_path, client=client)
    assert (tmp_path / model["path"]).read_bytes() == data
