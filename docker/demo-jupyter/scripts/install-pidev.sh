#!/usr/bin/env bash
set -euo pipefail
if command -v pi.dev >/dev/null 2>&1 || command -v pidev >/dev/null 2>&1 || command -v pi >/dev/null 2>&1; then
  (pi.dev --version || pidev --version || pi --version || true)
  exit 0
fi
if [[ -n "${PIDEV_INSTALL:-}" ]]; then
  echo "Running user-provided PIDEV_INSTALL..."
  bash -lc "$PIDEV_INSTALL"
  exit 0
fi
echo "pi.dev CLI was not found. Set PIDEV_INSTALL to the official pi.dev install command." >&2
exit 2
