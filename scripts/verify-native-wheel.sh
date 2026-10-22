#!/bin/sh
# Actual wheel + fresh dependencies, outside the checkout; CPU protocol fixtures.
# This is not model inference. Never installs NVIDIA packages/downloads models.
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
scratch=${TMPDIR:-${RUNNER_TEMP:-$HOME/.cache}}
mkdir -p "$scratch"
work=$(mktemp -d "$scratch/remesher-native-wheel.XXXXXX")
cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  if [ -n "${REMESHER_CI_REPORT_DIR:-}" ]; then
    mkdir -p "$REMESHER_CI_REPORT_DIR"
    for report in "$work/package.xml" "$work/plugin.xml"; do
      if [ -f "$report" ]; then cp "$report" "$REMESHER_CI_REPORT_DIR/"; fi
    done
  fi
  rm -rf -- "$work"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
uv build --wheel --out-dir "$work/dist" "$repo"
uv venv "$work/venv" --python "${REMESHER_TEST_PYTHON:-3.13}"
uv pip install --python "$work/venv/bin/python" "$work"/dist/*.whl pytest==9.1.1 pytest-subtests==0.15.0
# Legacy workflow tests consume the shipped example JSON explicitly as data.
# Do not copy src or add the checkout to the installed interpreter's path.
cp -R "$repo/examples" "$work/examples"
cd "$work"
unset PYTHONPATH
export HERMES_HOME="$work/hermes-profile"
export REMESHER_TEST_CLI="$work/venv/bin/comfy-prompt-cli"
export REMESHER_TEST_NATIVE_CLI="$REMESHER_TEST_CLI"
export REMESHER_TEST_NATIVE_PYTHON="$work/venv/bin/python"
"$work/venv/bin/python" -I -c 'from pathlib import Path; import comfy_prompt_cli; assert "site-packages" in Path(comfy_prompt_cli.__file__).parts; print(comfy_prompt_cli.__file__)'
for model in trellis2 pixal3d; do
  "$REMESHER_TEST_CLI" native-setup plan --root "$work/proposed-$model" --model "$model" > "$model.json"
done
"$work/venv/bin/python" -I -c 'import json; from pathlib import Path; reports=[json.loads(Path(m+".json").read_text()) for m in ("trellis2","pixal3d")]; assert [len(p["models"]) for p in reports] == [4,5]; assert not any(Path(p["config"]["venv"]).exists() for p in reports)'
"$work/venv/bin/python" -I -m pytest --import-mode=importlib -q \
  "$repo/tests" --junitxml="$work/package.xml"
"$work/venv/bin/python" "$repo/scripts/verify-test-report.py" "$work/package.xml"
# unittest fixtures import sibling test_plugin; use pytest prepend for this
# plugin-only partition, without adding the application checkout to sys.path.
"$work/venv/bin/python" -I -m pytest -q "$repo/integrations/hermes/tests" --junitxml="$work/plugin.xml"
"$work/venv/bin/python" "$repo/scripts/verify-test-report.py" "$work/plugin.xml"
uv pip check --python "$work/venv/bin/python"
