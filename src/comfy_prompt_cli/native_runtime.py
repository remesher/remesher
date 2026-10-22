"""Opt-in Linux/POSIX ComfyUI child ownership; never install or adopt a server."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import httpx


class LocalRuntime:
    def __init__(
        self,
        python: Path,
        checkout: Path,
        runs: Path,
        *,
        device: str = "cuda",
        models: Path | None = None,
        port: int = 0,
        startup_timeout: float = 120,
    ):
        if os.name != "posix":
            raise ValueError("native-local process ownership currently requires POSIX")
        if (
            not python.is_absolute()
            or not python.is_file()
            or not os.access(python, os.X_OK)
        ):
            raise ValueError("native Python must be an absolute existing executable")
        if not checkout.is_absolute() or not (checkout / "main.py").is_file():
            raise ValueError("native checkout must be absolute and contain main.py")
        if device not in {"cpu", "cuda"}:
            raise ValueError(
                "native device must be cpu or cuda (not a hardware certification)"
            )
        if not 0 <= port <= 65535 or startup_timeout <= 0:
            raise ValueError("invalid native port or startup timeout")
        if models is not None and (not models.is_absolute() or not models.is_dir()):
            raise ValueError("native models must be an absolute existing directory")
        self.models = models
        self.python, self.checkout, self.runs = python, checkout, runs
        self.device, self.port, self.startup_timeout = device, port, startup_timeout
        self.process = None
        self.log = None
        self.closed = False
        self.previous_sigterm = None
        self.terminated = False

    def __enter__(self):
        if self.closed or self.process is not None:
            raise ValueError("native runtime owners are single-use")
        if threading.current_thread() is not threading.main_thread():
            raise ValueError(
                "native-local ownership requires the main thread for signal cleanup"
            )
        # Reject busy ports before starting; argv identity below closes the
        # release/bind race without attaching to whoever wins that race.
        with socket.socket() as reservation:
            try:
                reservation.bind(("127.0.0.1", self.port))
            except OSError:
                raise ValueError("native-local port is already in use") from None
            self.port = reservation.getsockname()[1]
        self.runs.mkdir(parents=True, exist_ok=True)
        self.run_dir = Path(tempfile.mkdtemp(prefix="native-", dir=self.runs)).resolve()
        for name in ("input", "output", "user", "temp"):
            (self.run_dir / name).mkdir(mode=0o700)
        self.argv = [
            str(self.python),
            str(self.checkout / "main.py"),
            "--listen",
            "127.0.0.1",
            "--port",
            str(self.port),
            "--disable-all-custom-nodes",
            "--disable-api-nodes",
            "--disable-auto-launch",
        ]
        for name in ("input", "output", "user", "temp"):
            self.argv += [f"--{name}-directory", str(self.run_dir / name)]
        if self.models is not None:
            # JSON is a YAML subset: safe serialization for spaces/quotes/newlines.
            model_config = self.run_dir / "models.yaml"
            model_config.write_text(
                json.dumps(
                    {
                        "remesher": {
                            "base_path": str(self.models),
                            "is_default": True,
                            "diffusion_models": "diffusion_models",
                            "vae": "vae",
                            "clip_vision": "clip_vision",
                            "geometry_estimation": "geometry_estimation",
                        }
                    }
                )
            )
            self.argv += ["--extra-model-paths-config", str(model_config)]
        self.argv += ["--cpu"] if self.device == "cpu" else ["--cuda-device", "0"]
        self.base_url = f"http://127.0.0.1:{self.port}"
        try:
            self.previous_sigterm = signal.getsignal(signal.SIGTERM)
            signal.signal(signal.SIGTERM, self._terminate)
            self.log = (self.run_dir / "server.log").open("wb")
            self.process = subprocess.Popen(
                self.argv,
                cwd=self.checkout,
                stdin=subprocess.DEVNULL,
                stdout=self.log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            if self.terminated:
                raise SystemExit(128 + signal.SIGTERM)
            deadline = time.monotonic() + self.startup_timeout
            with httpx.Client(
                base_url=self.base_url,
                trust_env=False,
                follow_redirects=False,
                timeout=1,
            ) as client:
                while time.monotonic() < deadline:
                    if self.process.poll() is not None:
                        raise RuntimeError(
                            f"native ComfyUI exited ({self.process.returncode}); see {self.run_dir / 'server.log'}"
                        )
                    try:
                        response = client.get("/system_stats")
                        response.raise_for_status()
                        if (
                            response.json().get("system", {}).get("argv")
                            == self.argv[1:]
                            and self.process.poll() is None
                        ):
                            return self
                    except (httpx.HTTPError, ValueError, AttributeError):
                        pass
                    time.sleep(0.1)
            raise RuntimeError(
                f"native startup timed out or server identity differed; see {self.run_dir / 'server.log'}"
            )
        except BaseException:
            self.close()
            raise

    def _terminate(self, signum, frame):
        self.terminated = True
        # Popen may have created the new session before returning its handle.
        # Do not unwind until ownership is recorded and close() can reap it.
        if self.process is not None:
            raise SystemExit(128 + signum)

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.previous_sigterm is not None:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        if self.process is not None:
            # Only the session we created is kill authority. Never PID files,
            # named-process matching, /interrupt, or a pre-existing listener.
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.process.wait(timeout=5)
        if self.log is not None:
            self.log.close()
        if self.previous_sigterm is not None:
            signal.signal(signal.SIGTERM, self.previous_sigterm)

    def __exit__(self, *exc):
        self.close()
