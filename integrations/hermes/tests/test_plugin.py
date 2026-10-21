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

    def test_corrupt_store_returns_structured_unavailable(self):
        plugin, _ = self.fixture("pass\n")
        folder = plugin.data_root() / "jobs" / ("b" * 32)
        folder.mkdir(parents=True)
        (folder / "state.json").write_text("[]")
        self.assertEqual(plugin.job({"job_id": folder.name})["status"], "unavailable")

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
