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


def test_plugin_package_declares_truthful_compatibility():
    text = (ROOT / "integrations/hermes/plugin.yaml").read_text()
    assert 'requires_hermes: ">=0.22.2"' in text
    assert 'license: "Apache-2.0"' in text  # Owner-approved first-party license.
    assert "provides_hooks: []" in text
    assert "provides_middleware: []" in text


def test_plugin_readme_survives_subdirectory_install():
    text = (ROOT / "integrations/hermes/README.md").read_text()
    assert "../../docs/" not in text
    assert "--ref" in text
    assert "catalog" in text


def test_wheel_gate_includes_both_models_and_plugin_contracts():
    text = (ROOT / "scripts/verify-native-wheel.sh").read_text()
    assert "pixal3d" in text
    assert "REMESHER_TEST_NATIVE_CLI" in text
    assert "integrations/hermes/tests" in text
    assert "verify-test-report.py" in text
    assert 'License-Expression' in text
    assert 'License-File' in text
    assert 'dist.locate_file' in text


def test_apache_license_metadata_and_distributed_text():
    import hashlib
    import tomllib

    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["license"] == "Apache-2.0"
    assert project["license-files"] == ["LICENSE"]
    # Exact bytes from https://www.apache.org/licenses/LICENSE-2.0.txt.
    official_sha256 = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"
    license_bytes = (ROOT / "LICENSE").read_bytes()
    assert hashlib.sha256(license_bytes).hexdigest() == official_sha256
    assert (ROOT / "integrations/hermes/LICENSE").read_bytes() == license_bytes
    for dockerfile in ("docker/demo-jupyter/Dockerfile", "docker-example/runpod/Dockerfile"):
        assert any(line.startswith("COPY ") and "LICENSE" in line
                   for line in (ROOT / dockerfile).read_text().splitlines())
