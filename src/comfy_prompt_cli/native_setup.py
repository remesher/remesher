"""Explicit, pinned native model setup. No implicit installs or downloads."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import tempfile
import venv
from importlib.resources import files
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MANIFEST = json.loads(
    files(__package__).joinpath("native_setup_manifest.json").read_text()
)


class SetupConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    model: Literal["trellis2", "pixal3d"] = "trellis2"
    venv: Path
    checkout: Path
    models: Path
    runs: Path
    output: Path
    device: Literal["cpu", "cuda", "mps"] = "cuda"
    mps_fallback: bool = Field(default=True, strict=True)
    omp_num_threads: int | None = Field(default=None, ge=1, le=256, strict=True)
    minimum_memory_gib: int = Field(default=32, ge=1, le=1024)

    @field_validator("venv", "checkout", "models", "runs", "output")
    @classmethod
    def absolute_path(cls, value):
        if not value.is_absolute() or ".." in value.parts or value == Path("/"):
            raise ValueError("setup paths must be absolute non-root paths without '..'")
        return value

    @model_validator(mode="after")
    def separate_paths(self):
        paths = [self.venv, self.checkout, self.models, self.runs, self.output]
        if len(set(paths)) != len(paths):
            raise ValueError("setup paths must be distinct")
        # Model/output paths may be under checkout for existing installations,
        # but nothing may write inside the interpreter environment.
        for path in paths[1:]:
            if path.is_relative_to(self.venv) or self.venv.is_relative_to(path):
                raise ValueError("venv must not overlap other setup paths")
        return self

    @property
    def python(self):
        return self.venv / "bin" / "python"

    @property
    def runtime_environment(self):
        env = {}
        if self.device == "mps":
            env["PYTORCH_ENABLE_MPS_FALLBACK"] = "1" if self.mps_fallback else "0"
        threads = self.omp_num_threads
        if threads is None and self.device == "mps":
            threads = 1
        if threads is not None:
            env["OMP_NUM_THREADS"] = str(threads)
        return env

    @classmethod
    def at_root(cls, root):
        return cls(
            venv=root / "venv",
            checkout=root / "ComfyUI",
            models=root / "models",
            runs=root / "runs",
            output=root / "output",
            device="mps"
            if platform.system() == "Darwin" and platform.machine() == "arm64"
            else "cuda",
        )


def load_config(path: Path) -> SetupConfig:
    return SetupConfig.model_validate_json(path.read_text())


def selected_models(config: SetupConfig) -> list[dict]:
    if config.model == "trellis2":
        return MANIFEST["models"]
    return [
        m for m in MANIFEST["models"] if not m["path"].startswith("diffusion_models/")
    ] + MANIFEST["pixal3d"]


def installation_policy(config):
    if config.device == "mps" or platform.system() == "Darwin":
        return {
            "python": "3.12.12",
            "torch": "2.14.1",
            "torchvision": "0.29.1",
            "torch_index": "https://pypi.org/simple",
        }
    return {
        "torch": "2.10.0",
        "torchvision": "0.25.0",
        "torchaudio": "2.10.0",
        "torch_index": "https://download.pytorch.org/whl/"
        + ("cu130" if config.device == "cuda" else "cpu"),
    }


def plan(config: SetupConfig) -> dict:
    return {
        "operation": "plan",
        "config": config.model_dump(mode="json"),
        "comfy_revision": MANIFEST["comfy_revision"],
        "comfy_repository": MANIFEST["comfy_repository"],
        "models": selected_models(config),
        "download_bytes": sum(m["size"] for m in selected_models(config)),
        "install_requires": "--allow-install (dedicated venv only)",
        "download_requires": "--allow-download (weights only)",
        "installation": {
            **installation_policy(config),
            "requirements_sha256": REQUIREMENTS_SHA256,
            "package_download_bytes": None,
            "warning": "Package wheel downloads are additional to model bytes; transitive dependencies are not hash-locked",
            "global_mutation": False,
        },
        "generation_validated": False,
        "runtime_environment": config.runtime_environment,
        "memory_warning": "Low-memory MPS execution can require heavy system-volume swap; 8 GiB is not admitted without explicit --allow-low-memory. External weights do not relocate swap.",
    }


def macos_memory_status() -> dict:
    """Conservative free + inactive + speculative estimate, not swap capacity."""
    import re

    status = {
        "known": False,
        "source": "macos-vm-stat",
        "cgroup_detected": False,
        "controls": [],
        "effective_limit_bytes": None,
        "available_bytes": None,
    }
    try:

        def read(argv):
            return subprocess.run(
                argv, capture_output=True, text=True, check=True, timeout=10
            ).stdout

        total = int(read(["/usr/sbin/sysctl", "-n", "hw.memsize"]).strip())
        stats = read(["/usr/bin/vm_stat"])
        match = re.search(r"page size of (\d+) bytes", stats)
        if match is None:
            raise ValueError("Missing page size")
        page_size = int(match[1])
        pages = {
            key: int(value)
            for key, value in re.findall(
                r"^Pages (free|inactive|speculative):\s+(\d+)\.", stats, re.MULTILINE
            )
        }
        available = (
            sum(pages[key] for key in ("free", "inactive", "speculative")) * page_size
        )
        if total <= 0 or page_size <= 0 or available > total:
            raise ValueError("Invalid memory counters")
        status.update(
            known=True, effective_limit_bytes=total, available_bytes=available
        )
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        pass
    return status


def memory_status(proc: Path | None = None) -> dict:
    """Linux cgroup v1/v2 ancestors, not just misleading host RAM totals.

    No scope creation, limit changes, or attempts to leave a caller's cgroup.
    Unknown/unreadable control files fail closed at the admission boundary.
    """
    if proc is None and platform.system() == "Darwin":
        return macos_memory_status()
    proc = Path("/proc") if proc is None else proc
    limits, available, controls = [], [], []
    known = False
    detected = False
    try:
        mem = {
            line.split(":")[0]: int(line.split()[1]) * 1024
            for line in (proc / "meminfo").read_text().splitlines()
            if line.startswith(("MemTotal:", "MemAvailable:"))
        }
        limits.append(mem["MemTotal"])
        available.append(mem["MemAvailable"])
        groups = [
            line.split(":", 2)
            for line in (proc / "self/cgroup").read_text().splitlines()
        ]
        mounts = [
            line.split() for line in (proc / "self/mountinfo").read_text().splitlines()
        ]
        for _, controllers, group in groups:
            v2 = controllers == ""
            if not v2 and "memory" not in controllers.split(","):
                continue
            for mount in mounts:
                sep = mount.index("-")
                if mount[sep + 1] != ("cgroup2" if v2 else "cgroup"):
                    continue
                if not v2 and "memory" not in mount[sep + 3].split(","):
                    continue
                # mountinfo escapes whitespace using octal sequences.
                import re

                decode = lambda s: re.sub(
                    r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), s
                )
                root, point = Path(decode(mount[3])), Path(decode(mount[4]))
                group_path = Path(group)
                if ".." in group_path.parts or not group_path.is_relative_to(root):
                    continue
                leaf = point / group_path.relative_to(root)
                detected = True
                for directory in [leaf, *leaf.parents]:
                    if not directory.is_relative_to(point):
                        break
                    limit_file = directory / (
                        "memory.max" if v2 else "memory.limit_in_bytes"
                    )
                    if not limit_file.exists():
                        # The mount root may have no controller, but a leaf
                        # must expose it to establish an effective limit.
                        if directory == leaf:
                            raise ValueError("missing memory controller")
                        continue
                    raw = limit_file.read_text().strip()
                    controls.append({"path": str(limit_file), "limit": raw})
                    if raw != "max":
                        limit = int(raw)
                        current = int(
                            (
                                directory
                                / ("memory.current" if v2 else "memory.usage_in_bytes")
                            ).read_text()
                        )
                        limits.append(limit)
                        available.append(max(0, limit - current))
        known = detected
    except (OSError, ValueError, KeyError, IndexError):
        known = False
    return {
        "known": known,
        "cgroup_detected": detected,
        "controls": controls,
        "effective_limit_bytes": min(limits) if limits else None,
        "available_bytes": min(available) if available else None,
    }


def require_memory(config: SetupConfig, status: dict, *, allow_low_memory=False):
    minimum_gib = max(config.minimum_memory_gib, 32 if config.device == "mps" else 1)
    minimum = minimum_gib * 1024**3
    if not allow_low_memory and (
        not status["known"]
        or (status["available_bytes"] or 0) < minimum
        or (status["effective_limit_bytes"] or 0) < minimum
    ):
        raise ValueError(
            f"Insufficient or unknown effective memory; policy requires {minimum_gib} GiB. "
            "Use a sufficiently sized host (or approved bounded Linux scope/container), then re-run check. "
            "No resource limits are changed. --allow-low-memory acknowledges OOM and heavy system-disk swap risk for this invocation only; "
            "it does not raise limits or escape the scope."
        )


REQUIREMENTS_SHA256 = "7cdd0468c293cf87f09e35dacf8ace307f049d12fc53ad335c79f80d6ef81694"


def checkout_status(config):
    try:
        revision = subprocess.run(
            ["git", "-C", str(config.checkout), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            [
                "git",
                "-C",
                str(config.checkout),
                "status",
                "--porcelain",
                "--untracked-files=no",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
        digest = hashlib.sha256(
            (config.checkout / "requirements.txt").read_bytes()
        ).hexdigest()
        return {
            "ok": revision == MANIFEST["comfy_revision"]
            and not dirty
            and digest == REQUIREMENTS_SHA256,
            "revision": revision,
            "tracked_dirty": bool(dirty),
            "requirements_sha256": digest,
        }
    except (OSError, subprocess.SubprocessError):
        return {"ok": False, "error": "Missing/unreadable pinned ComfyUI checkout"}


PROBE = """import json,sys,platform
import torch, scipy, safetensors, aiohttp, yaml, comfy_kitchen
from importlib.metadata import version
cuda = torch.cuda.is_available()
mps = torch.backends.mps.is_available()
mps_tensor_ok = False
if sys.argv[1] == "mps" and mps:
    x = torch.ones((2, 2), device="mps")
    y = x @ x
    torch.mps.synchronize()
    mps_tensor_ok = y.device.type == "mps" and y.cpu().tolist() == [[2.0, 2.0], [2.0, 2.0]]
print(json.dumps({"ok":True,"prefix":sys.prefix,"base_prefix":sys.base_prefix,
    "python":platform.python_version(),"machine":platform.machine(),"platform":sys.platform,
    "torch":torch.__version__,"cuda_available":cuda,"cuda_version":torch.version.cuda,
    "mps_available":mps,"mps_tensor_ok":mps_tensor_ok,
    "device":torch.cuda.get_device_name(0) if cuda else None,
    "capability":list(torch.cuda.get_device_capability(0)) if cuda else None,
    "device_memory_bytes":torch.cuda.get_device_properties(0).total_memory if cuda else None,
    "comfy_kitchen":version("comfy-kitchen"),"comfy_aimdo":version("comfy-aimdo")}))
"""


def probe(config):
    if not config.python.is_file() or not (config.venv / "pyvenv.cfg").is_file():
        return {"ok": False, "error": "Missing dedicated Python venv"}
    try:
        result = subprocess.run(
            [str(config.python), "-I", "-c", PROBE, config.device],
            env={**os.environ, **config.runtime_environment},
            capture_output=True,
            text=True,
            timeout=45,
            check=True,
        )
        data = json.loads(result.stdout)
        if (
            Path(data["prefix"]).resolve() != config.venv.resolve()
            or data["prefix"] == data["base_prefix"]
        ):
            raise ValueError("Interpreter is not the configured venv")
        if config.device == "cuda" and not data["cuda_available"]:
            data.update(
                ok=False,
                error="CUDA unavailable; select device=cpu only as an unvalidated experimental path or repair CUDA",
            )
        if config.device == "mps" and not (
            data.get("mps_available") and data.get("mps_tensor_ok")
        ):
            data.update(
                ok=False,
                error="MPS unavailable or real MPS tensor probe failed; no CPU fallback accepted",
            )
        data["runtime_environment"] = config.runtime_environment
        data["generation_validated"] = False
        return data
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return {
            "ok": False,
            "error": "Venv capability probe failed; inspect interpreter/dependencies/CUDA/MPS tensor operation (45s deadline)",
        }


def check(config, *, allow_low_memory=False):
    from .native_download import no_symlinks, verified

    report = plan(config)
    report.update(
        operation="check",
        memory=memory_status(),
        capabilities=probe(config),
        checkout=checkout_status(config),
    )
    blockers = []
    if not report["checkout"]["ok"]:
        blockers.append(
            "Pinned clean checkout required; use --allow-install for a new checkout, never reset an existing checkout"
        )
    if not report["capabilities"]["ok"]:
        blockers.append(
            "Working dedicated venv required; --allow-install creates a managed venv but will not modify an existing unmanaged one"
        )
    states = []
    additional_bytes = 0
    for model in selected_models(config):
        path = config.models / model["path"]
        valid = verified(path, model)
        partial = path.with_suffix(path.suffix + ".part")
        no_symlinks(partial)
        partial_bytes = partial.stat().st_size if partial.is_file() else 0
        if not valid:
            additional_bytes += model["size"] - min(partial_bytes, model["size"])
        states.append(
            {
                **model,
                "verified": valid,
                "status": "verified"
                if valid
                else "invalid"
                if path.exists()
                else "missing",
            }
        )
    report["models"] = states
    report["additional_model_bytes"] = additional_bytes
    report["missing_model_bytes"] = sum(m["size"] for m in states if not m["verified"])
    if report["missing_model_bytes"]:
        blockers.append(
            "Missing/invalid pinned model contents; --allow-download authorizes only the selected preset's listed weights"
        )
    try:
        require_memory(config, report["memory"], allow_low_memory=allow_low_memory)
    except ValueError as exc:
        blockers.append(str(exc))
    report.update(
        ready=not blockers, blockers=blockers, low_memory_override=allow_low_memory
    )
    return report


def _run_install(argv, log, *, cwd=None):
    """Run only constructed argv; no user shell or arbitrary URL argument."""
    import signal
    import time

    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("PYTHON", "PIP_", "UV_", "GIT_"))
    }
    env.update(
        PIP_CONFIG_FILE=os.devnull,
        PIP_REQUIRE_VIRTUALENV="true",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_TERMINAL_PROMPT="0",
    )
    import threading

    if threading.current_thread() is not threading.main_thread():
        raise ValueError(
            "native installer ownership requires the main thread for signal cleanup"
        )
    child = None
    terminated = False

    def terminate(signum, frame):
        nonlocal terminated
        terminated = True
        # Defer unwinding during Popen until we have the owned child handle.
        if child is not None:
            raise SystemExit(128 + signum)

    previous_sigterm = signal.getsignal(signal.SIGTERM)
    try:
        signal.signal(signal.SIGTERM, terminate)
        with log.open("ab") as output:
            try:
                child = subprocess.Popen(
                    argv,
                    cwd=cwd,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                if terminated:
                    raise SystemExit(128 + signal.SIGTERM)
                if platform.system() == "Darwin":
                    deadline = time.monotonic() + 1800
                    while True:
                        if shutil.disk_usage(log.parent).free < 5 * 1024**3:
                            raise ValueError(
                                "macOS installer stopped: preserve 5 GiB runtime-volume disk reserve"
                            )
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise subprocess.TimeoutExpired(argv, 1800)
                        try:
                            code = child.wait(timeout=min(1, remaining))
                            break
                        except subprocess.TimeoutExpired:
                            continue
                else:
                    code = child.wait(timeout=1800)
                if code:
                    raise RuntimeError(f"Setup command failed ({code}); inspect {log}")
            finally:
                # Repeated SIGTERM must not cut short bounded group cleanup.
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
                if child is not None:
                    try:
                        os.killpg(child.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
                    # Kill descendants even when the direct child exited first.
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    child.wait(timeout=5)
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)


def install(config):
    from .native_download import file_lock, no_symlinks

    macos = platform.system() == "Darwin"
    if os.name != "posix" or platform.system() not in {"Linux", "Darwin"}:
        raise ValueError(
            "Automated installation supports Linux and Apple Silicon macOS only"
        )
    if macos and (platform.machine() != "arm64" or config.device == "cuda"):
        raise ValueError(
            "macOS installation requires Apple Silicon arm64 and device=mps or cpu"
        )
    if not macos and config.device == "mps":
        raise ValueError("MPS installation requires Apple Silicon macOS")
    policy = installation_policy(config)
    if macos and platform.python_version() != policy["python"]:
        raise ValueError(
            "macOS installation requires Python 3.12.12; run uv run --python 3.12.12 comfy-prompt-cli native-setup apply with the same arguments"
        )
    if macos:
        for destination in (config.venv, config.checkout):
            existing = destination
            while not existing.exists():
                existing = existing.parent
            if shutil.disk_usage(existing).free < 13 * 1024**3:
                raise ValueError(
                    "macOS installation requires 8 GiB package/checkout headroom plus 5 GiB disk reserve"
                )
    marker = config.venv / ".remesher-native-managed.json"
    no_symlinks(config.venv)
    no_symlinks(config.checkout)
    if config.venv.exists() and not marker.is_file():
        raise ValueError(
            "Refusing to modify an unmanaged venv; choose a new venv path or reuse it without --allow-install"
        )
    with (
        file_lock(config.venv.with_name(config.venv.name + ".setup.lock")),
        file_lock(config.checkout.with_name(config.checkout.name + ".setup.lock")),
    ):
        expected = {
            "schema_version": 1,
            "device": config.device,
            "comfy_revision": MANIFEST["comfy_revision"],
        }
        if macos:
            expected["installation"] = policy
        if config.venv.exists():
            no_symlinks(marker)
            if json.loads(marker.read_text()) != expected:
                raise ValueError("Managed venv profile changed; choose a new venv path")
        else:
            # An interrupted venv creation is deliberately not adopted automatically.
            venv.EnvBuilder(
                with_pip=True,
                system_site_packages=False,
                **({"symlinks": True} if macos else {}),
            ).create(config.venv)
            marker.write_text(json.dumps(expected))
        log = config.venv / "native-setup.log"
        no_symlinks(log)
        if not config.checkout.exists():
            config.checkout.parent.mkdir(parents=True, exist_ok=True)
            _run_install(["git", "init", str(config.checkout)], log)
        if not checkout_status(config)["ok"]:
            # Resume only an empty initialized repo, never reset an operator tree.
            contents = [p for p in config.checkout.iterdir() if p.name != ".git"]
            if contents:
                raise ValueError(
                    "Existing checkout is not clean at the pinned revision; choose a new checkout path"
                )
            _run_install(
                [
                    "git",
                    "-C",
                    str(config.checkout),
                    "fetch",
                    "--depth",
                    "1",
                    MANIFEST["comfy_repository"],
                    MANIFEST["comfy_revision"],
                ],
                log,
            )
            _run_install(
                [
                    "git",
                    "-C",
                    str(config.checkout),
                    "checkout",
                    "--detach",
                    "FETCH_HEAD",
                ],
                log,
            )
        if not checkout_status(config)["ok"]:
            raise ValueError(
                "Checkout revision/requirements digest did not match the pin"
            )
        # Do not invoke a global pip. A standard venv can expose a symlinked
        # interpreter, so confirm sys.prefix rather than resolving that symlink.
        identity = subprocess.run(
            [
                str(config.python),
                "-I",
                "-c",
                "import sys; print(sys.prefix); print(sys.base_prefix)",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.splitlines()
        if (
            len(identity) != 2
            or Path(identity[0]).resolve() != config.venv.resolve()
            or identity[0] == identity[1]
        ):
            raise ValueError("Refusing package mutation outside configured venv")
        pip = [
            str(config.python),
            "-I",
            "-m",
            "pip",
            "--isolated",
            "--require-virtualenv",
            "install",
            "--only-binary=:all:",
        ]
        packages = [
            f"{name}=={policy[name]}"
            for name in ("torch", "torchvision", "torchaudio")
            if name in policy
        ]
        _run_install(
            pip
            + [
                "--index-url",
                policy["torch_index"],
            ]
            + packages,
            log,
        )
        constraint = config.venv / "native-constraints.txt"
        no_symlinks(constraint)
        constraint.write_text("\n".join(packages) + "\n")
        _run_install(
            pip
            + [
                "--index-url",
                "https://pypi.org/simple",
                "-c",
                str(constraint),
                "-r",
                str(config.checkout / "requirements.txt"),
            ],
            log,
        )
        _run_install(
            [str(config.python), "-I", "-m", "pip", "--isolated", "check"], log
        )


def apply(
    config,
    config_path,
    *,
    allow_install=False,
    allow_download=False,
    allow_low_memory=False,
):
    from .native_download import download, no_symlinks

    before = check(config, allow_low_memory=allow_low_memory)
    try:
        require_memory(config, before["memory"], allow_low_memory=allow_low_memory)
    except ValueError:
        before["operation"] = "apply"
        return before
    # Independent approvals: no package changes or network model requests by default.
    if allow_install and (
        not before["capabilities"]["ok"] or not before["checkout"]["ok"]
    ):
        install(config)
    if allow_download:
        no_symlinks(config.models)
        existing = config.models
        while not existing.exists():
            existing = existing.parent
        if (
            before["additional_model_bytes"]
            and shutil.disk_usage(existing).free
            < before["additional_model_bytes"] + 1024**3
        ):
            raise ValueError(
                "Insufficient free disk for pinned weights plus 1 GiB margin"
            )
        for model in selected_models(config):
            download(model, config.models)
    after = check(config, allow_low_memory=allow_low_memory)
    after["operation"] = "apply"
    if after["ready"]:
        no_symlinks(config_path)
        content = (config.model_dump_json(indent=2) + "\n").encode("utf-8")
        try:
            existing = config_path.lstat()
        except FileNotFoundError:
            existing = None
        # Only reuse files with the same private ownership/mode and independent
        # inode that atomic publication would provide. Never bypass symlink checks.
        if (
            existing is not None
            and stat.S_ISREG(existing.st_mode)
            and stat.S_IMODE(existing.st_mode) == 0o600
            and existing.st_uid == os.geteuid()
            and existing.st_nlink == 1
            and config_path.read_bytes() == content
        ):
            after["config_path"] = str(config_path)
            return after
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=config_path.parent, prefix=".native-setup-", delete=False
        ) as output:
            temp_path = Path(output.name)
            try:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
                os.replace(temp_path, config_path)
            finally:
                temp_path.unlink(missing_ok=True)
        after["config_path"] = str(config_path)
    return after


def main(argv=None):
    import httpx

    class Parser(argparse.ArgumentParser):
        def error(self, message):
            raise ValueError(message)

    parser = Parser(description=__doc__)
    parser.add_argument("operation", choices=["plan", "check", "apply"])
    parser.add_argument(
        "--model",
        choices=["trellis2", "pixal3d"],
        help="Preset for --root; saved configs own model selection",
    )
    parser.add_argument(
        "--models",
        type=Path,
        help="With --root only: separate model storage, including an external volume",
    )
    parser.add_argument(
        "--device",
        choices=["cuda", "cpu", "mps"],
        help="With --root only: explicit device; Apple Silicon defaults to mps",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--root",
        type=Path,
        help="Absolute root; apply saves root/native-setup.json when ready",
    )
    source.add_argument(
        "--config", type=Path, help="JSON SetupConfig; paths must be absolute"
    )
    parser.add_argument(
        "--allow-install",
        action="store_true",
        help="Apply only: fetch pinned ComfyUI and install packages in a new/managed venv",
    )
    parser.add_argument(
        "--allow-download",
        action="store_true",
        help="Apply only: download the selected preset's SHA256-pinned weights",
    )
    parser.add_argument(
        "--allow-low-memory",
        action="store_true",
        help="Acknowledge OOM/heavy system-swap risk for this invocation; never changes resource limits",
    )
    try:
        args = parser.parse_args(argv)
        if args.operation != "apply" and (args.allow_install or args.allow_download):
            raise ValueError("Install/download opt-ins are accepted only by apply")
        config = (
            load_config(args.config) if args.config else SetupConfig.at_root(args.root)
        )
        overrides = {
            key: value
            for key, value in {"models": args.models, "device": args.device}.items()
            if value is not None
        }
        if overrides:
            if args.config:
                raise ValueError(
                    "--models and --device are only accepted with --root; saved configs own these settings"
                )
            config = SetupConfig.model_validate({**config.model_dump(), **overrides})
        if args.model is not None:
            if args.config:
                raise ValueError(
                    "--model is only accepted with --root; edit a separate config to change preset"
                )
            config.model = args.model
        if args.operation == "plan":
            report = plan(config)
            report["memory"] = memory_status()
        elif args.operation == "check":
            report = check(config, allow_low_memory=args.allow_low_memory)
        else:
            report = apply(
                config,
                args.config or args.root / "native-setup.json",
                allow_install=args.allow_install,
                allow_download=args.allow_download,
                allow_low_memory=args.allow_low_memory,
            )
        print(json.dumps(report, indent=2))
        return 0 if report.get("ready", True) else 1
    except (
        ValueError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        httpx.HTTPError,
    ) as exc:
        # Never echo signed redirect URLs/headers from transport exceptions.
        error = (
            "Download failed; retry apply to resume verified partials"
            if isinstance(exc, httpx.HTTPError)
            else str(exc)
        )
        print(json.dumps({"ok": False, "error": error, "generation_validated": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
