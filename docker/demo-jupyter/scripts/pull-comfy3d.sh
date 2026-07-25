#!/usr/bin/env bash
set -euo pipefail

PORT="${COMFY3D_PORT:-${COMFY_PORT:-8188}}"
CONFIG_PATH="${REMESHER_CONFIG_PATH:-config.json}"
LOCAL_URL="${COMFY3D_SERVER_URL:-${COMFYUI_SERVER_URL:-${COMFY_SERVER_URL:-http://127.0.0.1:${PORT}/}}}"

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

wait_for_comfy_url() {
  local url="$1"
  local attempts="${COMFY3D_WAIT_ATTEMPTS:-180}"
  local sleep_s="${COMFY3D_WAIT_SLEEP:-2}"
  echo "Waiting for ComfyUI/Comfy3D at $(normalize_url "$url")system_stats ..."
  for _ in $(seq 1 "$attempts"); do
    if check_comfy_url "$url"; then
      echo "ComfyUI/Comfy3D is reachable."
      write_config_url "$url"
      exit 0
    fi
    sleep "$sleep_s"
  done
  echo "ComfyUI/Comfy3D did not become reachable at $(normalize_url "$url")system_stats" >&2
  return 1
}

# RunPod's current default image is a combined Remesher+Comfy3D container.
# ComfyUI is started by /app/runpod/entrypoint.sh, so the notebook setup cell
# only has to wait for the local service and write config.json.
if [[ "${RUNPOD_COMBINED_COMFY3D:-0}" == "1" ]] || [[ -d /app/comfy && -f /app/comfy/main.py ]]; then
  wait_for_comfy_url "$LOCAL_URL"
fi

# Backward-compatible fallback for old/local control-image deployments: if an
# external URL is set, use it and skip Docker.
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

IMAGE="${COMFY3D_IMAGE:-michaelgold/comfy3d:latest}"
NAME="${COMFY3D_CONTAINER:-remesher-comfy3d}"
MODELS_DIR="${COMFY3D_MODELS_DIR:-/workspace/models/comfyui}"
OUTPUT_DIR="${COMFY3D_OUTPUT_DIR:-/workspace/output/comfyui}"
INPUT_DIR="${COMFY3D_INPUT_DIR:-/workspace/input}"

if ! command -v docker >/dev/null 2>&1; then
  cat >&2 <<'EOF'
Docker CLI is not installed in this notebook container.

Older Remesher control-image deployments start michaelgold/comfy3d with Docker,
so they require either:
  1. a mounted Docker socket at /var/run/docker.sock, or
  2. an already-running Comfy3D/ComfyUI server and COMFY3D_SERVER_URL set to its URL.

Current RunPod images should inherit from michaelgold/comfy3d and start ComfyUI
in-container. If you see this on RunPod, recreate the pod with the latest
michaelgold/remesher image.
EOF
  exit 2
fi

if ! docker info >/dev/null 2>&1; then
  cat >&2 <<'EOF'
Docker is available, but this notebook container cannot connect to a Docker daemon.

Older Remesher control-image deployments need /var/run/docker.sock mounted to
launch a sibling michaelgold/comfy3d container.

Current RunPod images no longer require Docker-in-notebook: they inherit from
michaelgold/comfy3d and start ComfyUI inside the same container. Recreate the pod
with the latest michaelgold/remesher image, or set COMFY3D_SERVER_URL to an
already-running Comfy3D endpoint.
EOF
  exit 2
fi

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
wait_for_comfy_url "http://127.0.0.1:${PORT}/" || {
  echo "ComfyUI did not become reachable. Last logs:" >&2
  docker logs --tail=240 "$NAME" >&2 || true
  exit 1
}
