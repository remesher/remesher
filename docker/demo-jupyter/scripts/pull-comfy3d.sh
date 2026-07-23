#!/usr/bin/env bash
set -euo pipefail
IMAGE="${COMFY3D_IMAGE:-michaelgold/comfy3d:latest}"
NAME="${COMFY3D_CONTAINER:-remesher-comfy3d}"
PORT="${COMFY3D_PORT:-8188}"
MODELS_DIR="${COMFY3D_MODELS_DIR:-/workspace/models/comfyui}"
OUTPUT_DIR="${COMFY3D_OUTPUT_DIR:-/workspace/output/comfyui}"
INPUT_DIR="${COMFY3D_INPUT_DIR:-/workspace/input}"
CONFIG_PATH="${REMESHER_CONFIG_PATH:-config.json}"

normalize_url() {
  local url="$1"
  url="${url%/}"
  printf '%s/' "$url"
}

check_comfy_url() {
  local url
  url="$(normalize_url "$1")"
  curl -fsS "${url}system_stats" >/dev/null 2>&1
}

write_config_url() {
  local url
  url="$(normalize_url "$1")"
  python3 - "$CONFIG_PATH" "$url" <<'PY'
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
url = sys.argv[2]
config = {}
if path.exists():
    try:
        config = json.loads(path.read_text())
    except Exception:
        config = {}
config['server_url'] = url
path.write_text(json.dumps(config, indent=2) + '\n')
print(f'Configured ComfyUI server_url: {url}')
PY
}

external_url="${COMFY3D_SERVER_URL:-${COMFYUI_SERVER_URL:-${COMFY_SERVER_URL:-}}}"
if [[ -n "$external_url" ]]; then
  echo "Using externally supplied Comfy3D/ComfyUI server: $external_url"
  if check_comfy_url "$external_url"; then
    write_config_url "$external_url"
    exit 0
  fi
  echo "Configured external ComfyUI URL is not reachable at ${external_url%/}/system_stats" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  cat >&2 <<'EOF'
Docker CLI is not installed in this notebook container.

This Remesher notebook image is a control/Jupyter image. Labs 1-3 start the separate
michaelgold/comfy3d runtime with Docker, so they require either:
  1. a mounted Docker socket at /var/run/docker.sock, or
  2. an already-running Comfy3D/ComfyUI server and COMFY3D_SERVER_URL set to its URL.
EOF
  exit 2
fi

if ! docker info >/dev/null 2>&1; then
  cat >&2 <<'EOF'
Docker is available, but this notebook container cannot connect to a Docker daemon.

Expected for the built-in RunPod notebook flow:
  /var/run/docker.sock mounted into the pod/container

Your error usually means the RunPod template/pod was launched without Docker socket access.
Relaunch with a template that exposes the Docker socket or mount:
  /var/run/docker.sock:/var/run/docker.sock

Alternative: start michaelgold/comfy3d separately and set one of these before this cell:
  COMFY3D_SERVER_URL=https://<your-comfy3d-endpoint>/
  COMFYUI_SERVER_URL=https://<your-comfy3d-endpoint>/

Then rerun this cell; the script will write config.json to that external server and skip Docker.
EOF
  exit 2
fi

# When this script runs inside the Jupyter container against the host Docker
# socket, docker run bind mounts must use host paths, not container paths.
# Resolve the host-side repo mount for /workspace/remesher automatically.
if [[ "$MODELS_DIR" == /workspace/* || "$OUTPUT_DIR" == /workspace/* || "$INPUT_DIR" == /workspace/* ]]; then
  REPO_HOST_PATH="$(docker inspect "${HOSTNAME:-}" --format '{{range .Mounts}}{{if eq .Destination "/workspace/remesher"}}{{.Source}}{{end}}{{end}}' 2>/dev/null || true)"
  if [[ -n "$REPO_HOST_PATH" ]]; then
    MODELS_DIR="${COMFY3D_MODELS_DIR:-$REPO_HOST_PATH/workspace/models/comfyui}"
    OUTPUT_DIR="${COMFY3D_OUTPUT_DIR:-$REPO_HOST_PATH/workspace/output/comfyui}"
    INPUT_DIR="${COMFY3D_INPUT_DIR:-$REPO_HOST_PATH/workspace/input}"
  fi
fi
mkdir -p "$MODELS_DIR" "$OUTPUT_DIR" "$INPUT_DIR"
echo "Pulling $IMAGE"
docker pull "$IMAGE"
echo "Starting $NAME on port $PORT"
docker rm -f "$NAME" >/dev/null 2>&1 || true
GPU_ARGS=()
if docker info 2>/dev/null | grep -qi "Runtimes:.*nvidia" || command -v nvidia-smi >/dev/null 2>&1; then GPU_ARGS=(--gpus all); fi
docker run -d --name "$NAME" "${GPU_ARGS[@]}" \
  -p "${PORT}:8188" \
  --add-host=host.docker.internal:host-gateway \
  -v "$MODELS_DIR:/app/comfy/models" \
  -v "$MODELS_DIR:/workspace/ComfyUI/models" \
  -v "$INPUT_DIR:/app/comfy/input" \
  -v "$INPUT_DIR:/workspace/ComfyUI/input" \
  -v "$OUTPUT_DIR:/app/comfy/output" \
  -v "$OUTPUT_DIR:/workspace/ComfyUI/output" \
  -e HF_TOKEN="${HF_TOKEN:-}" \
  "$IMAGE"
echo "Waiting for ComfyUI /system_stats..."
for i in $(seq 1 180); do
  if curl -fsS "http://host.docker.internal:${PORT}/system_stats" >/dev/null 2>&1 || curl -fsS "http://127.0.0.1:${PORT}/system_stats" >/dev/null 2>&1; then
    echo "ComfyUI is reachable."
    exit 0
  fi
  sleep 2
done
echo "ComfyUI did not become reachable. Last logs:" >&2
docker logs --tail=240 "$NAME" >&2 || true
exit 1
