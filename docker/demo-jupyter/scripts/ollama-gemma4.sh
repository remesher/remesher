#!/usr/bin/env bash
set -euo pipefail

MODEL="${OLLAMA_MODEL:-gemma4}"
OLLAMA_HOST_URL="${OLLAMA_HOST_URL:-http://127.0.0.1:11434}"
LOG_DIR="${OLLAMA_LOG_DIR:-/workspace/output/logs}"
LOG_FILE="$LOG_DIR/ollama.log"

mkdir -p "$LOG_DIR"

if ! command -v ollama >/dev/null 2>&1; then
  /workspace/remesher/docker/demo-jupyter/scripts/install-ollama.sh
fi

if ! curl -fsS "$OLLAMA_HOST_URL/api/tags" >/dev/null 2>&1; then
  # Do not trust pgrep alone: a stale/starting ollama process can exist while the API is unavailable.
  nohup ollama serve > "$LOG_FILE" 2>&1 &
fi

for _ in $(seq 1 120); do
  if curl -fsS "$OLLAMA_HOST_URL/api/tags" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl -fsS "$OLLAMA_HOST_URL/api/tags" >/dev/null 2>&1; then
  echo "Ollama server did not become ready at $OLLAMA_HOST_URL" >&2
  echo "Last Ollama logs:" >&2
  tail -120 "$LOG_FILE" >&2 || true
  exit 1
fi

ollama pull "$MODEL"
ollama list
