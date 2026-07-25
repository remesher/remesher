#!/usr/bin/env bash
set -euo pipefail
MODEL="${OLLAMA_MODEL:-gemma4}"
if ! command -v ollama >/dev/null 2>&1; then /workspace/remesher/docker/demo-jupyter/scripts/install-ollama.sh; fi
mkdir -p /workspace/output/logs
if ! pgrep -x ollama >/dev/null 2>&1; then nohup ollama serve > /workspace/output/logs/ollama.log 2>&1 & fi
for i in $(seq 1 90); do curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break || sleep 1; done
ollama pull "$MODEL"
ollama list
