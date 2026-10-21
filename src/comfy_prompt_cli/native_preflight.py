"""Read-only inventory of the pinned native ComfyUI 3D editor template.

This does not validate a runnable API graph, model contents, or hardware.
"""

from __future__ import annotations

import argparse
import json
from importlib.resources import files
from typing import Any
from urllib.parse import urlsplit

import httpx

MANIFEST = json.loads(files(__package__).joinpath("native_inventory.json").read_text())


# Deliberately partial schema sentinels, verified in nodes_trellis2.py at the
# manifest revision. Presence of other nodes is not full graph validation.
CONTRACTS = {
    "Trellis2Conditioning": (
        {"clip_vision_model": "CLIP_VISION", "image": "IMAGE"},
        ["CONDITIONING", "CONDITIONING"],
    ),
    "Pixal3DConditioning": (
        {
            "clip_vision_model": "CLIP_VISION",
            "image": "IMAGE",
            "camera_angle_x": "FLOAT",
        },
        ["CONDITIONING", "CONDITIONING"],
    ),
    "Trellis2ShapeStage": (
        {"positive": "CONDITIONING", "negative": "CONDITIONING", "voxel": "VOXEL"},
        ["CONDITIONING", "CONDITIONING", "LATENT"],
    ),
}


def inspect_inventory(
    object_info: dict[str, Any],
    models: dict[str, Any] | None = None,
) -> dict[str, Any]:
    models = models or {}
    missing_nodes = sorted(set(MANIFEST["nodes"]) - object_info.keys())
    missing_models = []
    for folder, name in MANIFEST["models"]:
        listed = models.get(folder)
        if not isinstance(listed, list) or name not in listed:
            missing_models.append(f"{folder}/{name}")
    mismatches = []
    for name, (inputs, outputs) in CONTRACTS.items():
        if name not in object_info:
            continue
        node = object_info[name]
        if not isinstance(node, dict) or not isinstance(node.get("input"), dict):
            mismatches.append(name)
            continue
        required = node["input"].get("required", {})
        if not isinstance(required, dict):
            mismatches.append(name)
            continue
        for key, expected in inputs.items():
            spec = required.get(key)
            if not isinstance(spec, list) or not spec or spec[0] != expected:
                mismatches.append(f"{name}.{key}")
        if node.get("output") != outputs:
            mismatches.append(f"{name}.output")
    return {
        "inventory_ok": not (missing_nodes or missing_models or mismatches),
        "missing_nodes": missing_nodes,
        "missing_models": sorted(missing_models),
        "schema_mismatches": sorted(mismatches),
        "schema_scope": sorted(CONTRACTS),
        "generation_validated": False,
        "hardware_validated": False,
        "workflow_api_validated": False,
        "reference": {
            k: v for k, v in MANIFEST.items() if k not in ("nodes", "models")
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--server",
        default="http://127.0.0.1:8188",
        help="Explicit local HTTP origin; numeric loopback only",
    )
    args = parser.parse_args(argv)
    try:
        url = urlsplit(args.server)
        if (
            url.scheme != "http"
            or url.hostname not in ("127.0.0.1", "::1")
            or url.username is not None
            or url.password is not None
            or url.path not in ("", "/")
            or url.query
            or url.fragment
            or (url.port is not None and not 1 <= url.port <= 65535)
        ):
            raise ValueError("expected a numeric loopback HTTP origin")
        with httpx.Client(
            base_url=args.server.rstrip("/"),
            timeout=5,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            stats = client.get("/system_stats")
            stats.raise_for_status()
            stats = stats.json()
            if not isinstance(stats, dict):
                raise TypeError("invalid system_stats")
            info = client.get("/object_info")
            info.raise_for_status()
            info = info.json()
            if not isinstance(info, dict):
                raise TypeError("invalid object_info")
            models = {}
            for folder in sorted({folder for folder, _ in MANIFEST["models"]}):
                response = client.get(f"/models/{folder}")
                if response.status_code == 404:
                    models[folder] = []
                    continue
                response.raise_for_status()
                listing = response.json()
                if not isinstance(listing, list) or not all(
                    isinstance(x, str) for x in listing
                ):
                    raise ValueError("invalid models listing")
                models[folder] = listing
        report = inspect_inventory(info, models)
        report["server_stats"] = stats
        result = 0 if report["inventory_ok"] else 1
    except (httpx.HTTPError, ValueError, TypeError):
        # Do not echo credentials, URLs, response bodies, or server exception text.
        report = {
            "inventory_ok": False,
            "generation_validated": False,
            "hardware_validated": False,
            "workflow_api_validated": False,
            "error": "Local preflight unavailable: check origin, server and JSON endpoints.",
        }
        result = 2
    print(json.dumps(report, indent=2))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
