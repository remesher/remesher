"""Run real pinned Hermes doctor + catalog validator, never fake SDK stubs.

CI sets PYTHONPATH to a separately checked-out immutable Hermes SDK revision.
Missing SDK/dependencies are failures, not skips or synthetic registrations.
"""
import json
from pathlib import Path
import sys


def main():
    try:
        # Require every lightweight SDK dependency explicitly, including those
        # optional core discovery might otherwise only warn about.
        import dotenv  # noqa: F401
        import httpx  # noqa: F401
        import packaging  # noqa: F401
        import psutil  # noqa: F401
        import requests  # noqa: F401
        import rich  # noqa: F401
        import ruamel.yaml  # noqa: F401
        import yaml  # noqa: F401
        from hermes_cli.plugin_dev import doctor_plugin
        from hermes_cli.plugin_validate import validate_plugin_dir
    except ImportError as exc:
        print(f"Missing Hermes SDK dependency: {exc}. Install scripts/hermes-sdk-requirements.txt and set PYTHONPATH to the pinned SDK.", file=sys.stderr)
        return 2
    target = Path(sys.argv[1]).resolve()
    doctor = doctor_plugin(target)
    print(doctor.format_text())
    validation = validate_plugin_dir(target)
    print(json.dumps(validation.to_dict(), indent=2))
    expected = {"remesher_health", "remesher_generate", "remesher_job", "remesher_assets"}
    if not doctor.ok or set(doctor.registered_tools) != expected or not validation.ok:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
