"""Release safety contracts; GPU acceptance is deliberately a separate gate."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_canonical_ci_runs_all_cpu_partitions():
    workflow = ROOT / ".github/workflows/ci.yml"
    assert workflow.is_file(), "canonical CPU CI must exist"
    text = workflow.read_text()
    for required in ("pull_request:", "push:", "lint:", "tests:", "wheel:", "plugin-sdk:",
                     "scripts/verify-native-wheel.sh", "scripts/verify-plugin-sdk.py",
                     "REMESHER_TEST_NATIVE_CLI", "REMESHER_TEST_CLI"):
        assert required in text
    assert "continue-on-error" not in text
    assert "self-hosted" not in text


def test_publishing_requires_explicit_release_dispatch():
    text = (ROOT / ".github/workflows/docker-publish.yml").read_text()
    triggers = text.split("permissions:")[0]
    assert "push:" not in triggers, "main integration must not publish Docker images"
    assert "publish:" in triggers
    assert "inputs.publish" in text


def test_sdk_missing_dependencies_fail_meaningfully():
    result = subprocess.run(
        [sys.executable, "-S", str(ROOT / "scripts/verify-plugin-sdk.py"),
         str(ROOT / "integrations/hermes")],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode != 0
    assert "Missing Hermes SDK dependency" in result.stderr


def test_wheel_gate_includes_both_models_and_plugin_contracts():
    text = (ROOT / "scripts/verify-native-wheel.sh").read_text()
    assert "pixal3d" in text
    assert "REMESHER_TEST_NATIVE_CLI" in text
    assert "integrations/hermes/tests" in text
    assert "verify-test-report.py" in text
