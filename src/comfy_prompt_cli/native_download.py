"""Size-bounded, content-verified downloads from packaged official HF pins."""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx


def no_symlinks(path: Path):
    for part in [path, *path.parents]:
        if part.is_symlink():
            raise ValueError(f"Refusing symlink in managed path: {part}")


def verified(path: Path, model: dict) -> bool:
    no_symlinks(path)
    if not path.is_file() or path.stat().st_size != model["size"]:
        return False
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() == model["sha256"]


@contextmanager
def file_lock(path: Path):
    no_symlinks(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError(
                f"Another setup owns {path}; retry after it finishes"
            ) from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _safe_url(url):
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or not (
            host == "huggingface.co" or host.endswith((".huggingface.co", ".hf.co"))
        )
    ):
        raise ValueError("Model redirect outside the official HTTPS HF allowlist")


def _transfer(client, url, part, model, deadline):
    offset = part.stat().st_size if part.exists() else 0
    if offset > model["size"]:
        raise ValueError("Partial model exceeds pinned size; remove the .part file")
    if offset == model["size"]:
        return
    headers = {"Accept-Encoding": "identity"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    for _ in range(8):
        _safe_url(url)
        with client.stream(
            "GET", url, headers=headers, follow_redirects=False
        ) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers.get("location", ""))
                _safe_url(url)
                continue
            response.raise_for_status()
            if response.status_code == 206:
                expected = f"bytes {offset}-{model['size'] - 1}/{model['size']}"
                if response.headers.get("content-range") != expected:
                    raise ValueError("Invalid Content-Range for pinned model")
                mode = "ab"
            elif response.status_code == 200:
                offset, mode = 0, "wb"  # server ignored Range: restart safely
            else:
                raise ValueError("Unexpected download status")
            with part.open(mode) as stream:
                for chunk in response.iter_bytes(1024 * 1024):
                    if time.monotonic() > deadline:
                        raise TimeoutError(
                            "Model download deadline exceeded; retry to resume"
                        )
                    if offset + len(chunk) > model["size"]:
                        raise ValueError("Download exceeds pinned size")
                    stream.write(chunk)
                    offset += len(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            if offset != model["size"]:
                raise httpx.ReadError("Incomplete pinned model; retry to resume")
            return
    raise ValueError("Too many model redirects")


def download(model: dict, root: Path, *, client=None, deadline_seconds=3600) -> str:
    """The CLI only passes bundled metadata, never user-supplied URLs/manifests."""
    relative = Path(model["path"])
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or model["repo"] not in {"Comfy-Org/TRELLIS.2", "Comfy-Org/Pixal3D", "Comfy-Org/MoGe"}
        or not re.fullmatch(r"[0-9a-f]{40}", model["revision"])
        or not re.fullmatch(r"[0-9a-f]{64}", model["sha256"])
        or model["size"] <= 0
    ):
        raise ValueError("Invalid bundled model metadata")
    target = root / relative
    part = target.with_suffix(target.suffix + ".part")
    with file_lock(target.with_suffix(target.suffix + ".lock")):
        no_symlinks(part)
        if verified(target, model):
            return "reused"
        if target.exists():
            raise ValueError(
                f"Existing model fails size/SHA256: {target}; move it aside explicitly"
            )
        if client is None:
            with httpx.Client(
                timeout=30, trust_env=False, follow_redirects=False
            ) as owned:
                return _download_locked(owned, model, part, target, deadline_seconds)
        return _download_locked(client, model, part, target, deadline_seconds)


def _download_locked(client, model, part, target, deadline_seconds):
    url = f"https://huggingface.co/{model['repo']}/resolve/{model['revision']}/{model['path']}"
    deadline = time.monotonic() + deadline_seconds
    for attempt in range(3):
        try:
            _transfer(client, url, part, model, deadline)
            break
        except (httpx.TransportError, httpx.HTTPStatusError):
            if attempt == 2 or time.monotonic() >= deadline:
                raise
            time.sleep(0.2 * (attempt + 1))
    if not verified(part, model):
        part.unlink(missing_ok=True)
        raise ValueError(
            "Downloaded model failed pinned size/SHA256; partial removed, retry explicitly"
        )
    os.replace(part, target)
    return "downloaded"
