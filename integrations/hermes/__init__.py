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
        workflow = Path(os.environ.get("REMESHER_WORKFLOW", ""))
        if not workflow.is_absolute() or not workflow.is_file():
            raise ValueError(
                "Set REMESHER_WORKFLOW to an existing absolute workflow JSON file"
            )
        timeout = args.get("timeout_seconds", 900)
        faces = args.get("target_face_num", 80000)
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
        }
        argv = [
            cfg["cli"],
            "image-to-glb",
            "--config",
            cfg["config"],
            "--workflow-file",
            str(workflow.resolve()),
            "--image",
            str(source),
            "--out-dir",
            str(folder / "output"),
            "--filename-prefix",
            "hermes_" + job_id,
            "--target-face-num",
            str(faces),
            "--timeout",
            str(timeout),
        ]
        (folder / "request.json").write_text(
            json.dumps({"argv": argv, "env": cli_environment()})
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


def settings():
    result = {}
    for key in ("CLI", "CONFIG"):
        value = os.environ.get("REMESHER_" + key, "")
        path = Path(value)
        if not value or not path.is_absolute() or not path.is_file():
            raise ValueError(
                "Set REMESHER_" + key + " to an existing absolute file path"
            )
        result[key.lower()] = str(path.resolve())
    if not os.access(result["cli"], os.X_OK):
        raise ValueError("REMESHER_CLI must be executable")
    return result


def cli_environment():
    # Do not leak Hermes credentials, Python import paths or uv activation into the CLI.
    return {
        k: v
        for k, v in os.environ.items()
        if k
        in {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR"}
    }


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
        with tempfile.TemporaryDirectory(prefix="remesher-health-") as temporary:
            code, timed_out = run_cli(
                [cfg["cli"], "health", "--config", cfg["config"]],
                Path(temporary),
                25,
                cli_environment(),
            )
        return {
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
            "Check configured ComfyUI connectivity; not GPU readiness.",
            {},
            [],
        ),
        (
            "remesher_generate",
            generate,
            "Submit one bounded image-to-GLB job to the configured ComfyUI server. Uploads the local image and uses GPU resources. Returns a job_id; poll remesher_job. Never automatically retry ambiguous failures.",
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
                "target_face_num": {
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
