#!/usr/bin/env bash
set -euo pipefail

MODEL="${OLLAMA_MODEL:-gemma4}"

if command -v pi >/dev/null 2>&1; then
  pi --version || pi --help || true
  exit 0
fi
if command -v pi.dev >/dev/null 2>&1; then
  pi.dev --version || pi.dev --help || true
  exit 0
fi
if command -v pidev >/dev/null 2>&1; then
  pidev --version || pidev --help || true
  exit 0
fi

if command -v ollama >/dev/null 2>&1; then
  if ! command -v npm >/dev/null 2>&1; then
    cat >&2 <<'EOF'
Ollama can install/launch Pi, but Pi's Ollama integration requires npm/Node.js.
This image should include Node.js 22+ and npm. If you are in an older running
container, rebuild/pull the updated image, then rerun this script.
EOF
    exit 4
  fi
  if ! node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 22 ? 0 : 1)' >/dev/null 2>&1; then
    echo "Ollama's Pi integration requires Node.js 22+; found $(node --version). Rebuild/pull the updated image." >&2
    exit 4
  fi

  echo "Installing/verifying Pi through Ollama launch integration..."
  # Ollama launch owns Pi's package installation and model wiring. Extra args
  # after -- are passed to Pi; --help keeps notebook smoke runs non-interactive.
  ollama launch pi --model "$MODEL" -y -- --help >/tmp/pi-ollama-launch-help.txt 2>&1 || {
    cat /tmp/pi-ollama-launch-help.txt >&2 || true
    exit 5
  }
  cat /tmp/pi-ollama-launch-help.txt
  exit 0
fi

if command -v pi >/dev/null 2>&1; then
  pi --version || pi --help || true
elif command -v pi.dev >/dev/null 2>&1; then
  pi.dev --version || pi.dev --help || true
elif command -v pidev >/dev/null 2>&1; then
  pidev --version || pidev --help || true
elif [[ -n "${PIDEV_INSTALL:-}" ]]; then
  echo "Running user-provided PIDEV_INSTALL..."
  bash -lc "$PIDEV_INSTALL"
elif command -v curl >/dev/null 2>&1; then
  echo "Falling back to official Pi installer: https://pi.dev/install.sh"
  curl -fsSL https://pi.dev/install.sh | sh
else
  echo "Pi CLI is not installed and neither Ollama launch nor curl installer path is available." >&2
  exit 2
fi

if command -v pi >/dev/null 2>&1; then
  pi --version || pi --help || true
elif command -v pi.dev >/dev/null 2>&1; then
  pi.dev --version || pi.dev --help || true
elif command -v pidev >/dev/null 2>&1; then
  pidev --version || pidev --help || true
else
  echo "Pi installer completed but no pi/pi.dev/pidev command is on PATH." >&2
  exit 3
fi
