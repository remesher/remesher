"""Remesher native Hermes plugin. No CLI dependencies enter Hermes's interpreter."""

import hashlib
import json
import math
import os
import re
import selectors
import shutil
import signal
import struct
import subprocess
import sys
import time
import uuid
from pathlib import Path


def data_root():
    from plugins.plugin_storage import plugin_data_dir

    return plugin_data_dir("remesher")


def save_state(folder, state):
    temporary = folder / (".state-" + uuid.uuid4().hex)
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(state, stream, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(folder / "state.json")
        descriptor = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def read_state(folder, *, observe_deadline=True):
    state = json.loads((folder / "state.json").read_text())
    if not isinstance(state, dict) or not isinstance(state.get("status"), str):
        raise TypeError("Malformed job state")
    if state["status"] in ("queued", "running") and (
        type(state.get("deadline")) not in (int, float)
        or not math.isfinite(state["deadline"])
    ):
        raise ValueError("Malformed job deadline")
    if (
        observe_deadline
        and state["status"] in ("queued", "running")
        and time.time() > state["deadline"] + 30
    ):
        state.update(
            status="interrupted",
            error="Worker did not finish; remote execution may still be active",
        )
    return state


def job(args):
    job_id = args.get("job_id", "")
    if not isinstance(job_id, str) or not re.fullmatch(r"[0-9a-f]{32}", job_id):
        return {
            "status": "invalid_request",
            "error": "job_id must be 32 lowercase hex characters",
        }
    try:
        folder = data_root() / "jobs" / job_id
        state = read_state(folder)
        if state["status"] == "succeeded":
            try:
                actual = collect_assets(folder)
                expected = state.get("assets")
                if (
                    not actual
                    or not isinstance(expected, list)
                    or sorted(actual, key=lambda item: item["path"])
                    != sorted(expected, key=lambda item: item["path"])
                ):
                    raise ValueError("Artifact manifest mismatch")
            except (OSError, ValueError, KeyError, TypeError):
                # Keep the original receipt intact: this is a current observation.
                state.update(
                    status="integrity_error",
                    assets=[],
                    error="Saved artifacts are missing, changed, or unreadable",
                )
        return state
    except FileNotFoundError:
        return {"status": "not_found", "job_id": job_id}
    except (OSError, ValueError, KeyError, TypeError):
        return {
            "status": "unavailable",
            "job_id": job_id,
            "error": "Cannot read job state",
        }


def assets(args):
    state = job(args)
    return {
        "status": state["status"],
        "job_id": state.get("job_id"),
        "assets": state.get("assets", []) if state["status"] == "succeeded" else [],
    }


def run_cli(argv, folder, timeout, env):
    """Drain output without buffering indefinitely; terminate the entire POSIX CLI group."""
    deadline = time.monotonic() + timeout
    with (folder / "cli.log").open("wb") as log:
        process = subprocess.Popen(
            argv,
            cwd=folder,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        assert process.stdout is not None
        timed_out = False
        kept = 0
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        timed_out = True
                        break
                    for key, _ in selector.select(min(remaining, 0.1)):
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        if kept < 1048576:
                            portion = chunk[: 1048576 - kept]
                            log.write(portion)
                            kept += len(portion)
                if not timed_out:
                    try:
                        process.wait(timeout=max(0.001, deadline - time.monotonic()))
                    except subprocess.TimeoutExpired:
                        timed_out = True
        finally:
            # native-local owns a separate server session. Give its SIGTERM
            # handler time to reap that session before forcibly killing the CLI.
            if (
                any(
                    argv[i : i + 2] == ["--backend", "native-local"]
                    for i in range(len(argv) - 1)
                )
                and process.poll() is None
            ):
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=12)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    pass
            # Also reap descendants retaining pipes or outliving the CLI parent.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            process.stdout.close()
        return process.returncode, timed_out


def collect_assets(folder, *, deadline=None, durable=False):
    found = []
    total_size = 0
    output = folder / "output"
    if output.is_symlink():
        raise ValueError("Artifact directory must not be a symlink")
    for index, path in enumerate(output.glob("*.glb")):
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("Artifact inspection deadline")
        if index >= 16:
            raise ValueError("Too many GLB artifacts (maximum 16)")
        if path.is_symlink() or not path.is_file():
            continue
        size = path.stat().st_size
        total_size += size
        if total_size > 512 * 1024 * 1024:
            raise ValueError("GLB artifacts exceed 512 MiB inspection budget")
        with path.open("rb") as stream:
            header = stream.read(12)
            if len(header) != 12 or struct.unpack("<4sII", header) != (
                b"glTF",
                2,
                size,
            ):
                continue
            digest = hashlib.sha256(header)
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError("Artifact inspection deadline")
                digest.update(chunk)
            if durable:
                os.fsync(stream.fileno())
        found.append(
            {
                "path": str(path),
                "size_bytes": size,
                "sha256": digest.hexdigest(),
                "media_type": "model/gltf-binary",
                "validation": "glb_header_only",
            }
        )
    if durable:
        descriptor = os.open(output, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return found


def worker(folder):
    import fcntl

    with (folder / ".worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        state = read_state(folder, observe_deadline=False)
        # A running receipt is ambiguous after a supervisor crash. Never replay.
        if state["status"] != "queued":
            return
        _worker_locked(folder, state)


def _worker_locked(folder, state):
    deadline = time.monotonic() + max(0, state["deadline"] - time.time())
    if time.time() >= state["deadline"]:
        state.update(
            status="timed_out",
            error="Local deadline expired before submission",
            finished_at=time.time(),
        )
        save_state(folder, state)
        return
    request = json.loads((folder / "request.json").read_text())
    state["status"] = "running"
    save_state(folder, state)
    try:
        if time.monotonic() >= deadline:
            raise TimeoutError("Local deadline expired before CLI launch")
        code, timed_out = run_cli(
            request["argv"],
            folder,
            max(0.001, deadline - time.monotonic()),
            request["env"],
        )
        state["returncode"] = code
        if timed_out or time.monotonic() >= deadline:
            raise TimeoutError("Local execution deadline")
        state["status"] = "failed"
        if code == 0:
            state["assets"] = collect_assets(folder, deadline=deadline, durable=True)
            if time.monotonic() >= deadline:
                raise TimeoutError("Artifact inspection deadline")
            state["status"] = "succeeded" if state["assets"] else "failed"
            if not state["assets"]:
                state["error"] = "CLI returned no valid GLB header"
        if state["status"] != "succeeded":
            state.setdefault(
                "error", "CLI failed or local deadline expired; inspect cli.log"
            )
    except TimeoutError:
        state.update(
            status="timed_out",
            assets=[],
            error="Local deadline expired; remote execution may still be active",
        )
    except (OSError, ValueError) as exc:
        state.update(
            status="failed", error=type(exc).__name__ + ": local worker failure"
        )
    state["finished_at"] = time.time()
    save_state(folder, state)


def generate(args):
    if os.name != "posix":
        return {
            "status": "unavailable",
            "error": "This first slice requires Linux/macOS (POSIX process groups)",
        }
    import fcntl

    try:
        root = data_root() / "jobs"
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (root / ".admission.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            for path in root.glob("*/state.json"):
                if read_state(path.parent)["status"] in ("queued", "running"):
                    return {
                        "status": "busy",
                        "error": "One local job is already active; poll its job_id",
                    }
            return _generate(args)
    except (OSError, ValueError, KeyError, TypeError):
        return {"status": "unavailable", "error": "Cannot access persistent job store"}


def _generate(args):
    folder = None
    state = None
    try:
        cfg = settings()
        image = Path(args.get("image", ""))
        if (
            not image.is_absolute()
            or not image.is_file()
            or image.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp")
        ):
            raise ValueError("image must be an existing absolute PNG/JPEG/WebP file")
        if image.stat().st_size > 20 * 1024 * 1024:
            raise ValueError("image exceeds 20 MiB")
        if cfg["backend"] == "comfy3d":
            cfg["workflow"] = existing_path(cfg.get("workflow", ""), "workflow")
        timeout = args.get("timeout_seconds", 900)
        faces = args.get("target_face_num", 80000)
        no_decimation = args.get("no_decimation", False)
        if type(no_decimation) is not bool:
            raise ValueError("no_decimation must be a boolean")
        if no_decimation and cfg["backend"] == "comfy3d":
            raise ValueError("no_decimation requires a native backend")
        repair = args.get("mesh_repair", "none")
        if repair not in ("none", "fill", "solid"):
            raise ValueError("mesh_repair must be none, fill or solid")
        if repair != "none" and (cfg["backend"] == "comfy3d" or not no_decimation):
            raise ValueError("mesh_repair requires a native backend and no_decimation")
        resolution = args.get("repair_resolution", 512)
        perimeter = args.get("repair_max_perimeter", 0.03)
        small = args.get("repair_drop_small_components", 0.005)
        if type(resolution) is not int or not 32 <= resolution <= 2048:
            raise ValueError("repair_resolution must be an integer from 32 to 2048")
        for value, upper, name in ((perimeter, 0.03, "repair_max_perimeter"),
                                   (small, 0.5, "repair_drop_small_components")):
            if type(value) not in (int, float) or not 0 <= value <= upper:
                raise ValueError(f"{name} must be finite and between 0 and {upper}")
        if type(timeout) is not int or not 1 <= timeout <= 1800:
            raise ValueError("timeout_seconds must be an integer from 1 to 1800")
        if type(faces) is not int or not 1000 <= faces <= 200000:
            raise ValueError("target_face_num must be an integer from 1000 to 200000")
        root = data_root() / "jobs"
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        job_id = uuid.uuid4().hex
        folder = root / job_id
        folder.mkdir(mode=0o700)
        source = folder / ("input" + image.suffix.lower())
        shutil.copyfile(image, source)
        (folder / "output").mkdir()
        state = {
            "schema_version": 1,
            "job_id": job_id,
            "status": "queued",
            "created_at": time.time(),
            "deadline": time.time() + timeout,
            "assets": [],
            "log_path": str(folder / "cli.log"),
            "remote_cancellation_supported": False,
            "backend": cfg["backend"],
        }
        argv = [
            cfg["cli"],
            "image-to-glb",
            *backend_arguments(cfg, folder),
            "--image",
            str(source),
            *([] if "native_config" in cfg else ["--out-dir", str(folder / "output")]),
            "--filename-prefix",
            "hermes_" + job_id,
            *(["--no-decimation"] if no_decimation else ["--target-face-num", str(faces)]),
            *(["--mesh-repair", repair, "--repair-resolution", str(resolution),
               "--repair-max-perimeter", str(perimeter),
               "--repair-drop-small-components", str(small)] if repair != "none" else []),
            "--timeout",
            str(timeout),
        ]
        (folder / "request.json").write_text(
            json.dumps({"argv": argv, "env": cli_environment(cfg)})
        )
        save_state(folder, state)
        child = subprocess.Popen(
            [sys.executable, "-I", str(Path(__file__).resolve()), str(folder)],
            cwd=folder,
            env=cli_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        # Keep a reaper thread, not a daemon worker: the independent supervisor owns the deadline.
        import threading

        threading.Thread(target=child.wait, daemon=True).start()
        return state
    except (OSError, ValueError, TypeError) as exc:
        if folder is not None and state is not None:
            state.update(status="failed", error="Could not launch local worker")
            save_state(folder, state)
            return state
        return {"status": "invalid_request", "error": str(exc)}


ENVIRONMENT_KEYS = {
    "CUDA_VISIBLE_DEVICES",
    "HF_HOME",
    "HF_HUB_CACHE",
    "TORCH_HOME",
    "XDG_CACHE_HOME",
    "LD_LIBRARY_PATH",
    "PYTORCH_CUDA_ALLOC_CONF",
}
SETTING_KEYS = {
    "cli",
    "backend",
    "config",
    "workflow",
    "native_python",
    "native_config",
    "native_checkout",
    "native_device",
    "native_model",
    "native_server",
    "environment",
}


def existing_path(value, label, *, executable=False, directory=False):
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError(f"{label} must be an existing absolute path")
    path = Path(value)
    if not path.is_absolute() or not (path.is_dir() if directory else path.is_file()):
        raise ValueError(f"{label} must be an existing absolute path")
    if executable and not os.access(path, os.X_OK):
        raise ValueError(f"{label} must be executable")
    # Do NOT resolve interpreter symlinks: venv identity depends on the invoked path.
    return str(path)


def read_native_config(filename):
    """Dependency-free schema-v1 inspection; CLI still owns full readiness checks."""
    config = json.loads(Path(filename).read_text())
    keys = {"venv", "checkout", "models", "runs", "output"}
    if not isinstance(config, dict) or not keys <= config.keys():
        raise ValueError("native_config requires the five runtime paths")
    if config.keys() - keys - {"schema_version", "device", "minimum_memory_gib", "model"}:
        raise ValueError("native_config contains unsupported keys")
    if config.get("model", "trellis2") not in ("trellis2", "pixal3d"):
        raise ValueError("native_config model must be trellis2 or pixal3d")
    if (
        type(config.get("schema_version", 1)) is not int
        or config.get("schema_version", 1) != 1
    ):
        raise ValueError("native_config requires schema_version 1")
    if config.get("device", "cuda") not in ("cuda", "cpu"):
        raise ValueError("native_config device must be cuda or cpu")
    memory = config.get("minimum_memory_gib", 32)
    if type(memory) is not int or not 1 <= memory <= 1024:
        raise ValueError(
            "native_config minimum_memory_gib must be an integer from 1 to 1024"
        )
    paths = {}
    for key in keys:
        value = config[key]
        if not isinstance(value, str) or "\x00" in value:
            raise ValueError("native_config paths must be strings without NUL")
        path = Path(value)
        if not path.is_absolute() or path == Path("/") or ".." in path.parts:
            raise ValueError(
                "native_config paths must be absolute non-root paths without '..'"
            )
        paths[key] = path
    if len(set(paths.values())) != len(paths):
        raise ValueError("native_config paths must be distinct")
    venv = paths.pop("venv")
    if any(
        path.is_relative_to(venv) or venv.is_relative_to(path)
        for path in paths.values()
    ):
        raise ValueError("native_config venv must not overlap other paths")
    return config


def validate_settings(raw):
    from urllib.parse import urlsplit

    if not isinstance(raw, dict) or raw.keys() - SETTING_KEYS:
        raise ValueError("Settings must be an object with only documented keys")
    cfg = dict(raw)
    cfg.setdefault("backend", "comfy3d")
    if cfg["backend"] not in ("comfy3d", "native", "native-local"):
        raise ValueError("backend must be comfy3d, native or native-local")
    cfg["cli"] = existing_path(cfg.get("cli"), "cli", executable=True)
    if "native_config" in cfg:
        if cfg["backend"] != "native-local":
            raise ValueError("native_config requires native-local")
        if cfg.keys() & {
            "native_python",
            "native_checkout",
            "native_device",
            "native_server",
        }:
            raise ValueError(
                "native_config cannot be combined with explicit runtime settings"
            )
        config = read_native_config(existing_path(cfg["native_config"], "native_config"))
        model = config.get("model", "trellis2")
        if "native_model" in cfg and cfg["native_model"] != model:
            raise ValueError("native_model conflicts with native_config model")
        cfg["native_model"] = model
    if cfg["backend"] == "comfy3d":
        cfg["config"] = existing_path(cfg.get("config"), "config")
    else:
        cfg.setdefault("native_model", "trellis2")
        if cfg["native_model"] not in ("trellis2", "pixal3d"):
            raise ValueError("native_model must be trellis2 or pixal3d")
        if cfg["backend"] == "native-local" and "native_config" in cfg:
            cfg["native_config"] = existing_path(cfg["native_config"], "native_config")
            read_native_config(cfg["native_config"])
        elif cfg["backend"] == "native-local":
            cfg["native_python"] = existing_path(
                cfg.get("native_python"), "native_python", executable=True
            )
            cfg["native_checkout"] = existing_path(
                cfg.get("native_checkout"), "native_checkout", directory=True
            )
            existing_path(
                str(Path(cfg["native_checkout"]) / "main.py"), "native_checkout/main.py"
            )
            cfg.setdefault("native_device", "cuda")
            if cfg["native_device"] not in ("cuda", "cpu"):
                raise ValueError("native_device must be cuda or cpu")
        else:
            cfg.setdefault("native_server", "http://127.0.0.1:8188")
            server = cfg["native_server"]
            if not isinstance(server, str) or any(
                c.isspace() or ord(c) < 32 for c in server
            ):
                raise ValueError("native_server must be a numeric loopback HTTP origin")
            url = urlsplit(server)
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
                raise ValueError("native_server must be a numeric loopback HTTP origin")
    environment = cfg.setdefault("environment", {})
    if not isinstance(environment, dict) or environment.keys() - ENVIRONMENT_KEYS:
        raise ValueError("environment contains unsupported keys")
    for key, value in environment.items():
        if not isinstance(value, str) or "\x00" in value or "\n" in value:
            raise ValueError("environment values must be single-line strings")
        if key in {
            "HF_HOME",
            "HF_HUB_CACHE",
            "TORCH_HOME",
            "XDG_CACHE_HOME",
            "LD_LIBRARY_PATH",
        }:
            paths = value.split(":") if key == "LD_LIBRARY_PATH" else [value]
            if any(not p or not Path(p).is_absolute() for p in paths):
                raise ValueError("cache/library environment paths must be absolute")
    return cfg


def settings():
    filename = os.environ.get("REMESHER_SETTINGS")
    if filename:
        path = existing_path(filename, "REMESHER_SETTINGS")
        return validate_settings(json.loads(Path(path).read_text()))
    return validate_settings(
        {
            key: os.environ["REMESHER_" + key.upper()]
            for key in SETTING_KEYS - {"environment"}
            if "REMESHER_" + key.upper() in os.environ
        }
    )


def backend_arguments(cfg, folder):
    if cfg["backend"] == "comfy3d":
        # Preserve compatibility with legacy CLIs that predate --backend.
        return ["--config", cfg["config"], "--workflow-file", cfg["workflow"]]
    argv = ["--backend", cfg["backend"], "--native-model", cfg["native_model"]]
    if cfg["backend"] == "native":
        return argv + ["--native-server", cfg["native_server"]]
    if "native_config" in cfg:
        # Snapshot configuration per job; never mutate the operator's config or
        # mix its output/run roots with the plugin's artifact ownership boundary.
        config = read_native_config(cfg["native_config"])
        config.update(runs=str(folder / "native-runs"), output=str(folder / "output"))
        snapshot = folder / "native-setup.json"
        descriptor = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(config, stream, allow_nan=False)
        return argv + ["--native-config", str(snapshot)]
    for name in ("native_python", "native_checkout", "native_device"):
        argv += ["--" + name.replace("_", "-"), cfg[name]]
    return argv + ["--native-runs", str(folder / "native-runs")]


def cli_environment(cfg=None):
    # Native cache/device/library settings are explicit, never ambient secrets or activation.
    env = {
        k: v
        for k, v in os.environ.items()
        if k
        in {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR"}
    }
    if cfg is not None:
        env.update(cfg["environment"])
    return env


def health(args):
    if os.name != "posix":
        return {
            "status": "unavailable",
            "error": "POSIX required",
            "gpu_generation_verified": False,
        }
    import tempfile

    try:
        cfg = settings()
        if cfg["backend"] == "native-local":
            return {
                "status": "configured",
                "backend": cfg["backend"],
                "scope": "configuration_only",
                "gpu_generation_verified": False,
                "model_visibility_verified": False,
                **{
                    key: cfg[key]
                    for key in (
                        "native_config",
                        "native_python",
                        "native_checkout",
                        "native_device",
                    )
                    if key in cfg
                },
                "native_model": cfg["native_model"],
            }
        with tempfile.TemporaryDirectory(prefix="remesher-health-") as temporary:
            config = cfg.get("config")
            if cfg["backend"] == "native":
                config = str(Path(temporary) / "config.json")
                Path(config).write_text(
                    json.dumps({"server_url": cfg["native_server"]})
                )
            code, timed_out = run_cli(
                [cfg["cli"], "health", "--config", config],
                Path(temporary),
                25,
                cli_environment(cfg),
            )
        return {
            "backend": cfg["backend"],
            "scope": "connectivity_only",
            "status": "timed_out"
            if timed_out
            else "healthy"
            if code == 0
            else "unhealthy",
            "returncode": code,
            "gpu_generation_verified": False,
        }
    except (OSError, ValueError) as exc:
        return {
            "status": "unavailable",
            "error": str(exc),
            "gpu_generation_verified": False,
        }


def register(ctx):
    job_properties = {"job_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"}}
    definitions = [
        (
            "remesher_health",
            health,
            "Check server connectivity, or native-local configuration without starting it; never GPU readiness.",
            {},
            [],
        ),
        (
            "remesher_generate",
            generate,
            "Submit one bounded image-to-GLB job using the configured comfy3d, native or native-local backend. Uploads the local image; native-local starts an owned server and may use GPU resources. Returns a job_id; poll remesher_job. Never automatically retry ambiguous failures.",
            {
                "image": {
                    "type": "string",
                    "description": "Absolute local PNG/JPEG/WebP path (max 20 MiB)",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1800,
                    "default": 900,
                },
                "no_decimation": {
                    "type": "boolean",
                    "default": False,
                    "description": "Native only: bypass simplification with no face/vertex cap; retain UV/PBR export.",
                },
                "mesh_repair": {
                    "type": "string", "enum": ["none", "fill", "solid"],
                    "description": "Opt-in native Torch/SciPy repair before UV/PBR; requires no_decimation. No new NVIDIA-only dependencies. Default none.",
                },
                "repair_resolution": {
                    "type": "integer", "minimum": 32, "maximum": 2048,
                    "description": "Solid remesh grid, default 512; generation resolution unchanged, no face cap.",
                },
                "repair_max_perimeter": {
                    "type": "number", "minimum": 0, "maximum": 0.03,
                    "description": "Small-hole perimeter in mesh units, default .03; 0 skips fill. No open-chain fill.",
                },
                "repair_drop_small_components": {
                    "type": "number", "minimum": 0, "maximum": 0.5,
                    "description": "Solid remesh component fraction of largest, default .005; 0 retains all.",
                },
                "target_face_num": {
                    "description": "Simplified face target; ignored when no_decimation is true.",
                    "type": "integer",
                    "minimum": 1000,
                    "maximum": 200000,
                    "default": 80000,
                },
            },
            ["image"],
        ),
        (
            "remesher_job",
            job,
            "Read a persisted job status by job_id.",
            job_properties,
            ["job_id"],
        ),
        (
            "remesher_assets",
            assets,
            "List persisted GLB artifact paths and SHA-256 hashes for a successful job.",
            job_properties,
            ["job_id"],
        ),
    ]
    for name, function, description, properties, required in definitions:

        def handler(args, _function=function, **kwargs):
            if not isinstance(args, dict):
                return json.dumps(
                    {
                        "status": "invalid_request",
                        "error": "Arguments must be an object",
                    }
                )
            return json.dumps(_function(args))

        ctx.register_tool(
            name=name,
            toolset="remesher",
            schema={
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
            },
            handler=handler,
            check_fn=lambda: True,
        )
    ctx.register_skill(
        "remesher", Path(__file__).parent / "skills" / "remesher" / "SKILL.md"
    )


if __name__ == "__main__":
    worker(Path(sys.argv[1]))
