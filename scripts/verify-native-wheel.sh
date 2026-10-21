#!/bin/sh
# Build the actual wheel, install separately, exercise packaged native interfaces.
# This runs protocol/setup fixtures only, not GPU inference or model downloads.
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
work=$(mktemp -d "${TMPDIR:-$HOME/.cache}/remesher-native-wheel.XXXXXX")
trap 'rm -rf -- "$work"' EXIT HUP INT TERM
uv build --wheel --out-dir "$work/dist" "$repo"
uv venv "$work/venv"
uv pip install --python "$work/venv/bin/python" "$work"/dist/*.whl pytest
cd "$work"
unset PYTHONPATH
"$work/venv/bin/python" -I -c 'from pathlib import Path; import comfy_prompt_cli; assert "site-packages" in Path(comfy_prompt_cli.__file__).parts; print(comfy_prompt_cli.__file__)'
"$work/venv/bin/comfy-prompt-cli" native-setup plan --root "$work/proposed" > "$work/plan.json"
"$work/venv/bin/python" -I -c 'import json; from pathlib import Path; p=json.loads(Path("plan.json").read_text()); assert len(p["models"]) == 4; assert not Path("proposed").exists()'
"$work/venv/bin/python" -I -m pytest --import-mode=importlib -q \
  "$repo/tests/test_native_setup.py" "$repo/tests/test_native_setup_boundaries.py" \
  "$repo/tests/test_native_cli.py" "$repo/tests/test_native_runtime.py" \
  "$repo/tests/test_native_backend.py" "$repo/tests/test_native_preflight.py"
