#!/usr/bin/env python3
"""Inspect plugin settings; optionally publish to a NEW explicit file. No installs."""

import argparse
import importlib.util
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", required=True, type=Path, help="Candidate settings JSON"
    )
    parser.add_argument(
        "--output", type=Path, help="New absolute settings file (never overwrite)"
    )
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location(
        "remesher_configuration", Path(__file__).resolve().parents[1] / "__init__.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        cfg = module.validate_settings(json.loads(args.input.read_text()))
        if cfg["backend"] == "comfy3d":
            cfg["workflow"] = module.existing_path(cfg.get("workflow"), "workflow")
        report = {
            "status": "configured",
            "settings": cfg,
            "gpu_generation_verified": False,
            "model_visibility_verified": False,
        }
        if cfg["backend"] == "native-local" and "native_config" in cfg:
            report["model_note"] = (
                "Run the configured CLI native-setup check --config on native_config. "
                "Configuration inspection does not verify setup or GPU readiness."
            )
        elif cfg["backend"] == "native-local":
            checkout = Path(cfg["native_checkout"])
            model = "trellis_2" if cfg["native_model"] == "trellis2" else "pixal3d"
            names = [
                f"diffusion_models/{model}_int8_convrot.safetensors",
                "clip_vision/dino_v3_L_naf_fp32.safetensors",
                "vae/trellis_2_shape_vae_bf16.safetensors",
                "vae/trellis_2_texture_vae_bf16.safetensors",
            ]
            report["default_model_files_present"] = {
                name: (checkout / "models" / name).is_file() for name in names
            }
            report["extra_model_paths_file_present"] = (
                checkout / "extra_model_paths.yaml"
            ).is_file()
            report["model_note"] = (
                "File existence only; extra paths are not parsed. Native /object_info validation is authoritative."
            )
        if args.output:
            if not args.output.is_absolute():
                raise ValueError("output must be absolute")
            # O_EXCL refuses existing files AND symlinks; no active profile defaults.
            descriptor = os.open(
                args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            with os.fdopen(descriptor, "w") as stream:
                json.dump(cfg, stream, indent=2, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            report["written"] = str(args.output)
        print(json.dumps(report, indent=2))
        return 0
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({"status": "invalid_configuration", "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
