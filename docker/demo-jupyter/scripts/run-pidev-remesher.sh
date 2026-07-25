#!/usr/bin/env bash
set -euo pipefail

ROOT="${REMESHER_WORKDIR:-/workspace/remesher}"
SKILL="${REMESHER_CLI_SKILL:-$ROOT/skills/remesher-cli/SKILL.md}"
OUTPUT_DIR="${REMESHER_AGENT_OUTPUT_DIR:-/workspace/output/agent}"
MODEL="${OLLAMA_MODEL:-gemma4}"
OLLAMA_URL="${OLLAMA_HOST:-http://127.0.0.1:11434}"

mkdir -p "$OUTPUT_DIR"
cd "$ROOT"

export OLLAMA_HOST="$OLLAMA_URL"
export OLLAMA_MODEL="$MODEL"
export REMESHER_CLI_SKILL="$SKILL"
export REMESHER_WORKDIR="$ROOT"
export REMESHER_AGENT_OUTPUT_DIR="$OUTPUT_DIR"

if [[ ! -f "$SKILL" ]]; then
  echo "Remesher CLI skill not found: $SKILL" >&2
  exit 3
fi

bash docker/demo-jupyter/scripts/ollama-gemma4.sh
bash docker/demo-jupyter/scripts/install-pidev.sh

cat <<EOF
Launching Pi for Remesher
- Working directory: $ROOT
- Skill: $SKILL
- Ollama: $OLLAMA_HOST
- Model: $OLLAMA_MODEL
- Output dir: $OUTPUT_DIR
EOF

exec ollama launch pi --model "$OLLAMA_MODEL" -y --   --skill "$SKILL"   --approve   "$@"
