"""CPU-only contract tests; fake CLI processes are not GPU generation evidence."""

import importlib.util
import json
import os
import struct
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


from typing import Any


def load_plugin() -> Any:
    spec = importlib.util.spec_from_file_location(
        "remesher_plugin", ROOT / "__init__.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_state_sync_failure_preserves_previous_receipt(self):
        plugin = load_plugin()
        plugin.save_state(self.root, {"status": "queued"})
        with (
            patch.object(plugin.os, "fsync", side_effect=OSError("disk unavailable")),
            self.assertRaises(OSError),
        ):
            plugin.save_state(self.root, {"status": "succeeded"})
        self.assertEqual(
            json.loads((self.root / "state.json").read_text()), {"status": "queued"}
        )
        self.assertEqual(list(self.root.glob(".state-*")), [])

    def test_health_uses_explicit_cli_and_scrubs_python_environment(self):
        self.assertTrue(
            (ROOT / "__init__.py").exists(), "native plugin entrypoint missing"
        )
        plugin = load_plugin()
        cli = self.root / "cli with spaces"
        cli.write_text(
            '#!/usr/bin/python3\nimport os,sys,pathlib\nassert "PYTHONPATH" not in os.environ\nassert "UV_PROJECT_ENVIRONMENT" not in os.environ\nassert "API_KEY" not in os.environ\nassert sys.argv[1] == "health" and sys.argv[2] == "--config" and pathlib.Path(sys.argv[3]).is_file()\nprint("Connected to ComfyUI")\n'
        )
        cli.chmod(0o700)
        config = self.root / "config.json"
        config.write_text("{}")
        with patch.dict(
            os.environ,
            {
                "REMESHER_CLI": str(cli),
                "REMESHER_CONFIG": str(config),
                "PYTHONPATH": "poison",
                "UV_PROJECT_ENVIRONMENT": "poison",
                "API_KEY": "not-forwarded",
            },
        ):
            result = plugin.health({})
        self.assertEqual(result["status"], "healthy")
        self.assertFalse(result["gpu_generation_verified"])

    def fixture(self, body):
        plugin = load_plugin()
        plugin.data_root = lambda: self.root / "state"
        cli = self.root / "fake cli"
        cli.write_text("#!/usr/bin/python3\nimport sys, pathlib, struct, time\n" + body)
        cli.chmod(0o700)
        config = self.root / "config.json"
        config.write_text("{}")
        workflow = self.root / "workflow.json"
        workflow.write_text("{}")
        image = self.root / "image ; $bad.png"
        image.write_bytes(b"fixture-image")
        env = patch.dict(
            os.environ,
            {
                "REMESHER_CLI": str(cli),
                "REMESHER_CONFIG": str(config),
                "REMESHER_WORKFLOW": str(workflow),
            },
        )
        env.start()
        self.addCleanup(env.stop)
        return plugin, image

    def wait_job(self, plugin, job_id):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            result = plugin.job({"job_id": job_id})
            if result["status"] not in ("queued", "running"):
                return result
            time.sleep(0.03)
        self.fail("job did not reach terminal state")

    def test_generate_persists_job_and_validated_artifacts(self):
        plugin, image = self.fixture("""
assert sys.argv[1] == "image-to-glb"
assert pathlib.Path(sys.argv[sys.argv.index("--image") + 1]).read_bytes() == b"fixture-image"
assert "--workflow-file" in sys.argv and "--timeout" in sys.argv
out = pathlib.Path(sys.argv[sys.argv.index("--out-dir") + 1])
out.mkdir(exist_ok=True)
(out / "mesh.glb").write_bytes(struct.pack("<4sII", b"glTF", 2, 12))
""")
        self.assertTrue(hasattr(plugin, "generate"), "job lifecycle missing")
        result = plugin.generate({"image": str(image), "timeout_seconds": 5})
        self.assertEqual(result["status"], "queued")
        final = self.wait_job(plugin, result["job_id"])
        self.assertEqual(final["status"], "succeeded", final)
        reloaded = load_plugin()
        reloaded.data_root = plugin.data_root
        assets = reloaded.assets({"job_id": result["job_id"]})
        self.assertEqual(len(assets["assets"]), 1)
        self.assertTrue(Path(assets["assets"][0]["path"]).is_file())
        self.assertEqual(assets["assets"][0]["size_bytes"], 12)

    def test_manifest_order_does_not_change_integrity(self):
        plugin, _ = self.fixture("pass\n")
        folder = plugin.data_root() / "jobs" / ("d" * 32)
        (folder / "output").mkdir(parents=True)
        for name in ("first.glb", "second.glb"):
            (folder / "output" / name).write_bytes(struct.pack("<4sII", b"glTF", 2, 12))
        manifest = plugin.collect_assets(folder)
        plugin.save_state(
            folder, {"status": "succeeded", "assets": list(reversed(manifest))}
        )
        self.assertEqual(plugin.job({"job_id": folder.name})["status"], "succeeded")

    def test_success_reads_revalidate_manifest_after_restart(self):
        plugin, image = self.fixture(
            'out = pathlib.Path(sys.argv[sys.argv.index("--out-dir") + 1]); (out / "mesh.glb").write_bytes(struct.pack("<4sII", b"glTF", 2, 16) + b"data")\n'
        )
        result = plugin.generate({"image": str(image), "timeout_seconds": 5})
        final = self.wait_job(plugin, result["job_id"])
        self.assertEqual(final["status"], "succeeded")
        path = Path(final["assets"][0]["path"])
        original = path.read_bytes()
        reloaded = load_plugin()
        reloaded.data_root = plugin.data_root
        for mutation in ("changed", "deleted", "symlink"):
            with self.subTest(mutation=mutation):
                path.unlink(missing_ok=True)
                if mutation == "changed":
                    path.write_bytes(original[:-4] + b"oops")
                elif mutation == "symlink":
                    outside = self.root / "outside.glb"
                    outside.write_bytes(original)
                    path.symlink_to(outside)
                observed = reloaded.job({"job_id": result["job_id"]})
                self.assertEqual(observed["status"], "integrity_error")
                self.assertEqual(observed["assets"], [])
                self.assertEqual(
                    reloaded.assets({"job_id": result["job_id"]})["assets"], []
                )
        path.unlink(missing_ok=True)
        path.write_bytes(original)
        self.assertEqual(
            reloaded.job({"job_id": result["job_id"]})["status"], "succeeded"
        )

    def test_admission_is_bounded_to_one_active_job(self):
        plugin, image = self.fixture("time.sleep(0.4)\n")
        first = plugin.generate({"image": str(image), "timeout_seconds": 2})
        second = plugin.generate({"image": str(image), "timeout_seconds": 2})
        self.wait_job(plugin, first["job_id"])
        if "job_id" in second:
            self.wait_job(plugin, second["job_id"])
        self.assertEqual(second["status"], "busy")

    def test_spawn_failure_is_persisted_not_left_queued(self):
        plugin, image = self.fixture("pass\n")
        with patch.object(
            plugin.subprocess, "Popen", side_effect=OSError("spawn unavailable")
        ):
            result = plugin.generate({"image": str(image)})
        states = list((self.root / "state" / "jobs").glob("*/state.json"))
        self.assertEqual(len(states), 1)
        self.assertEqual(json.loads(states[0].read_text())["status"], "failed")
        self.assertEqual(result["status"], "failed")

    def test_register_declares_four_json_tools_and_bundled_skill(self):
        plugin = load_plugin()

        class Context:
            def __init__(self):
                self.tools = {}
                self.skills = {}

            def register_tool(self, name, **kwargs):
                self.tools[name] = kwargs

            def register_skill(self, name, path, **kwargs):
                self.skills[name] = path

        ctx = Context()
        self.assertTrue(hasattr(plugin, "register"), "Hermes registration missing")
        plugin.register(ctx)
        self.assertEqual(
            set(ctx.tools),
            {"remesher_health", "remesher_generate", "remesher_job", "remesher_assets"},
        )
        self.assertTrue(ctx.skills["remesher"].is_file())
        reply = json.loads(
            ctx.tools["remesher_job"]["handler"]({"job_id": "../escape"})
        )
        self.assertEqual(reply["status"], "invalid_request")

    def test_timeout_kills_local_process_and_caps_log(self):
        plugin, image = self.fixture(
            'print("x" * 2000000, flush=True)\ntime.sleep(60)\n'
        )
        start = time.monotonic()
        result = plugin.generate({"image": str(image), "timeout_seconds": 1})
        final = self.wait_job(plugin, result["job_id"])
        self.assertEqual(final["status"], "timed_out")
        self.assertLess(time.monotonic() - start, 4)
        self.assertLessEqual(Path(final["log_path"]).stat().st_size, 1048576)
        self.assertFalse(final["remote_cancellation_supported"])

    def test_nonzero_and_missing_and_invalid_glb_are_failures(self):
        for body in (
            "sys.exit(3)\n",
            "pass\n",
            'out = pathlib.Path(sys.argv[sys.argv.index("--out-dir") + 1]); (out / "bad.glb").write_bytes(b"not-glb")\n',
        ):
            with self.subTest(body=body[:12]):
                plugin, image = self.fixture(body)
                result = plugin.generate({"image": str(image), "timeout_seconds": 2})
                final = self.wait_job(plugin, result["job_id"])
                self.assertEqual(final["status"], "failed")
                self.assertEqual(
                    plugin.assets({"job_id": result["job_id"]})["assets"], []
                )

    def test_reject_invalid_requests_without_spawning(self):
        plugin, image = self.fixture("pass\n")
        for extra in (
            {"timeout_seconds": True},
            {"timeout_seconds": 1801},
            {"timeout_seconds": float("nan")},
            {"target_face_num": 0},
            {"image": "relative.png"},
            {"image": None},
        ):
            with (
                self.subTest(extra=extra),
                patch.object(plugin.subprocess, "Popen") as spawn,
            ):
                self.assertEqual(
                    plugin.generate({"image": str(image), **extra})["status"],
                    "invalid_request",
                )
                spawn.assert_not_called()
        for bad_id in ("../escape", "A" * 32, None, 1):
            self.assertEqual(
                plugin.job({"job_id": bad_id})["status"], "invalid_request"
            )
        self.assertEqual(plugin.job({"job_id": "0" * 32})["status"], "not_found")

    def test_expired_worker_is_interrupted_not_retried(self):
        plugin, _ = self.fixture("pass\n")
        folder = plugin.data_root() / "jobs" / ("a" * 32)
        folder.mkdir(parents=True)
        plugin.save_state(
            folder,
            {"job_id": folder.name, "status": "running", "deadline": time.time() - 100},
        )
        self.assertEqual(plugin.job({"job_id": folder.name})["status"], "interrupted")

    def test_health_uses_group_bounded_runner(self):
        plugin, _ = self.fixture("pass\n")
        with patch.object(plugin, "run_cli", return_value=(-9, True)) as runner:
            result = plugin.health({})
        self.assertEqual(result["status"], "timed_out")
        self.assertEqual(runner.call_args.args[2], 25)

    def test_asset_collection_rejects_symlinked_output_directory(self):
        plugin, _ = self.fixture("pass\n")
        folder = self.root / "job"
        folder.mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "mesh.glb").write_bytes(struct.pack("<4sII", b"glTF", 2, 12))
        (folder / "output").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            plugin.collect_assets(folder)

    def test_asset_inspection_rejects_excessive_files(self):
        plugin, _ = self.fixture("pass\n")
        folder = self.root / "assets"
        (folder / "output").mkdir(parents=True)
        for i in range(17):
            (folder / "output" / f"{i}.glb").write_bytes(
                struct.pack("<4sII", b"glTF", 2, 12)
            )
        with self.assertRaises(ValueError):
            plugin.collect_assets(folder)

    def test_nonfinite_and_boolean_deadlines_fail_closed(self):
        plugin, _ = self.fixture("pass\n")
        folder = plugin.data_root() / "jobs" / ("c" * 32)
        folder.mkdir(parents=True)
        for deadline in (float("nan"), float("inf"), True):
            with self.subTest(deadline=str(deadline)):
                (folder / "state.json").write_text(
                    json.dumps({"status": "queued", "deadline": deadline})
                )
                self.assertEqual(
                    plugin.job({"job_id": folder.name})["status"], "unavailable"
                )

    def test_corrupt_store_returns_structured_unavailable(self):
        plugin, _ = self.fixture("pass\n")
        folder = plugin.data_root() / "jobs" / ("b" * 32)
        folder.mkdir(parents=True)
        (folder / "state.json").write_text("[]")
        self.assertEqual(plugin.job({"job_id": folder.name})["status"], "unavailable")

    def test_worker_syncs_artifact_before_success_receipt(self):
        import stat

        plugin, _ = self.fixture("pass\n")
        folder = self.root / "sync-job"
        (folder / "output").mkdir(parents=True)
        artifact = folder / "output" / "mesh.glb"
        artifact.write_bytes(struct.pack("<4sII", b"glTF", 2, 12))
        plugin.save_state(
            folder,
            {"job_id": "a" * 32, "status": "queued", "deadline": time.time() + 5},
        )
        (folder / "request.json").write_text(
            json.dumps({"argv": ["unused"], "env": {}})
        )
        events = []
        real_sync, real_save = plugin.os.fsync, plugin.save_state

        def sync(fd):
            info = os.fstat(fd)
            if info.st_ino == artifact.stat().st_ino and stat.S_ISREG(info.st_mode):
                events.append("artifact")
            real_sync(fd)

        def save(folder, state):
            events.append(state["status"])
            real_save(folder, state)

        with (
            patch.object(plugin.os, "fsync", side_effect=sync),
            patch.object(plugin, "save_state", side_effect=save),
            patch.object(plugin, "run_cli", return_value=(0, False)),
        ):
            plugin.worker(folder)
        self.assertIn("artifact", events)
        self.assertLess(events.index("artifact"), events.index("succeeded"))

    def test_deadline_during_running_receipt_prevents_submission(self):
        plugin, _ = self.fixture("pass\n")
        folder = self.root / "delayed-receipt"
        folder.mkdir()
        plugin.save_state(
            folder,
            {"job_id": "a" * 32, "status": "queued", "deadline": time.time() + 0.1},
        )
        (folder / "request.json").write_text(json.dumps({"argv": ["never"], "env": {}}))
        real_save = plugin.save_state

        def slow_save(folder, state):
            real_save(folder, state)
            if state["status"] == "running":
                time.sleep(0.2)

        with (
            patch.object(plugin, "save_state", side_effect=slow_save),
            patch.object(plugin, "run_cli", return_value=(0, False)) as run,
        ):
            plugin.worker(folder)
        run.assert_not_called()
        self.assertEqual(plugin.read_state(folder)["status"], "timed_out")

    def test_worker_rejects_success_after_inspection_deadline(self):
        plugin, _ = self.fixture("pass\n")
        folder = self.root / "late-result"
        folder.mkdir()
        plugin.save_state(
            folder,
            {"job_id": "a" * 32, "status": "queued", "deadline": time.time() + 0.1},
        )
        (folder / "request.json").write_text(
            json.dumps({"argv": ["unused"], "env": {}})
        )

        def slow_inspection(*args, **kwargs):
            time.sleep(0.2)
            return [{"path": "unverified"}]

        with (
            patch.object(plugin, "run_cli", return_value=(0, False)),
            patch.object(plugin, "collect_assets", side_effect=slow_inspection),
        ):
            plugin.worker(folder)
        state = plugin.read_state(folder)
        self.assertEqual(state["status"], "timed_out")
        self.assertEqual(state["assets"], [])
        self.assertIn("remote", state["error"])

    def test_worker_lock_excludes_concurrent_supervisor(self):
        import fcntl

        plugin, _ = self.fixture("pass\n")
        folder = self.root / "locked-worker"
        folder.mkdir()
        original = {"status": "queued", "deadline": time.time() + 5}
        plugin.save_state(folder, original)
        with (folder / ".worker.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with patch.object(plugin, "_worker_locked") as run:
                plugin.worker(folder)
            run.assert_not_called()
            self.assertEqual(plugin.read_state(folder), original)
        with patch.object(plugin, "_worker_locked") as run:
            plugin.worker(folder)
        run.assert_called_once()

    def test_worker_never_replays_running_or_terminal_jobs(self):
        plugin, _ = self.fixture("pass\n")
        folder = self.root / "replay"
        folder.mkdir()
        (folder / "request.json").write_text(json.dumps({"argv": ["never"], "env": {}}))
        for status in ("running", "succeeded", "failed", "timed_out", "interrupted"):
            with self.subTest(status=status):
                original = {
                    "job_id": "a" * 32,
                    "status": status,
                    "deadline": time.time() + 10,
                }
                plugin.save_state(folder, original)
                with patch.object(plugin, "run_cli", return_value=(0, False)) as run:
                    plugin.worker(folder)
                run.assert_not_called()
                self.assertEqual(
                    json.loads((folder / "state.json").read_text()), original
                )

    def test_delayed_worker_does_not_submit_after_deadline(self):
        plugin, _ = self.fixture("pass\n")
        folder = self.root / "delayed"
        folder.mkdir()
        plugin.save_state(
            folder,
            {"job_id": "a" * 32, "status": "queued", "deadline": time.time() - 100},
        )
        (folder / "request.json").write_text(json.dumps({"argv": ["never"], "env": {}}))
        with patch.object(plugin, "run_cli", return_value=(0, False)) as run:
            plugin.worker(folder)
        run.assert_not_called()
        self.assertEqual(plugin.read_state(folder)["status"], "timed_out")

    def test_concurrent_admission_allows_only_one_submission(self):
        from concurrent.futures import ThreadPoolExecutor

        plugin, image = self.fixture("time.sleep(0.4)\n")
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda _: plugin.generate(
                        {"image": str(image), "timeout_seconds": 2}
                    ),
                    range(2),
                )
            )
        self.assertEqual(sorted(item["status"] for item in results), ["busy", "queued"])
        accepted = next(item for item in results if item["status"] == "queued")
        self.wait_job(plugin, accepted["job_id"])

    def test_timeout_terminates_descendants(self):
        marker = self.root / "descendant-survived"
        plugin, image = self.fixture(
            "import os\nif os.fork() == 0:\n    time.sleep(2)\n    pathlib.Path("
            + repr(str(marker))
            + ").write_text('alive')\n    os._exit(0)\ntime.sleep(60)\n"
        )
        result = plugin.generate({"image": str(image), "timeout_seconds": 1})
        self.assertEqual(self.wait_job(plugin, result["job_id"])["status"], "timed_out")
        time.sleep(1.3)
        self.assertFalse(marker.exists(), "descendant escaped local deadline")


if __name__ == "__main__":
    unittest.main()
