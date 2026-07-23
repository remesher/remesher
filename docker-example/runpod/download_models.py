#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests
from huggingface_hub import hf_hub_download, snapshot_download


def to_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_config(config_url: str) -> list[dict]:
    if config_url.startswith("http://") or config_url.startswith("https://"):
        resp = requests.get(config_url, timeout=60)
        resp.raise_for_status()
        data = resp.json()
    else:
        data = json.loads(Path(config_url).read_text(encoding="utf-8"))

    if not isinstance(data, list):
        raise ValueError("model_config must be a JSON array")
    return data


def main() -> int:
    config_url = os.getenv(
        "MODEL_CONFIG_URL",
        "https://raw.githubusercontent.com/michaelgold/ComfyUI-HF-Model-Downloader/main/model_config.json",
    )
    models_root = Path(os.getenv("COMFY_MODELS_DIR", "/app/comfy/models"))
    allow_protected = to_bool(os.getenv("ALLOW_PROTECTED_MODELS", "0"))
    skip_existing = to_bool(os.getenv("SKIP_EXISTING_MODELS", "1"), default=True)

    print(f"[model-downloader] Loading model config from: {config_url}")
    print(f"[model-downloader] Target model root: {models_root}")

    try:
        entries = load_config(config_url)
    except Exception as exc:
        print(f"[model-downloader] Failed to load config: {exc}")
        return 1

    downloaded = 0
    skipped = 0
    failed = 0

    for idx, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            print(f"[model-downloader] [{idx}] Invalid entry type; skipping")
            skipped += 1
            continue

        repo_id = (entry.get("repo_id") or "").strip()
        subfolder = (entry.get("subfolder") or "").strip()
        filename = (entry.get("filename") or "").strip()
        local_path = str(entry.get("local_path") or "").strip().strip("\n")
        protected = bool(entry.get("protected", False))

        if not repo_id or not local_path:
            print(f"[model-downloader] [{idx}] Missing repo_id/local_path; skipping")
            skipped += 1
            continue

        if protected and not allow_protected:
            print(f"[model-downloader] [{idx}] Protected model skipped: {repo_id}")
            skipped += 1
            continue

        target = models_root / local_path

        try:
            if filename:
                target.parent.mkdir(parents=True, exist_ok=True)
                if skip_existing and target.exists():
                    print(f"[model-downloader] [{idx}] Exists, skipping: {target}")
                    skipped += 1
                    continue

                kwargs = {
                    "repo_id": repo_id,
                    "filename": filename,
                    "local_dir": str(target.parent),
                    "local_dir_use_symlinks": False,
                    "resume_download": True,
                }
                if subfolder:
                    kwargs["subfolder"] = subfolder

                hf_hub_download(**kwargs)
                downloaded += 1
                print(f"[model-downloader] [{idx}] Downloaded: {target}")
            else:
                target.mkdir(parents=True, exist_ok=True)
                if skip_existing and any(target.iterdir()):
                    print(f"[model-downloader] [{idx}] Directory non-empty, skipping: {target}")
                    skipped += 1
                    continue

                allow_patterns = None
                if subfolder:
                    allow_patterns = [f"{subfolder}/**"]

                snapshot_download(
                    repo_id=repo_id,
                    local_dir=str(target),
                    local_dir_use_symlinks=False,
                    allow_patterns=allow_patterns,
                    resume_download=True,
                )
                downloaded += 1
                print(f"[model-downloader] [{idx}] Snapshot downloaded: {target}")
        except Exception as exc:
            failed += 1
            print(
                f"[model-downloader] [{idx}] Failed: repo={repo_id} local={target} error={exc}"
            )

    print(
        f"[model-downloader] Done. downloaded={downloaded} skipped={skipped} failed={failed}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
