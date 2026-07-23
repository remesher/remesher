#!/usr/bin/env bash
set -euo pipefail
IMAGE="${COMFY3D_IMAGE:-michaelgold/comfy3d:latest}"
NAME="${COMFY3D_CONTAINER:-remesher-comfy3d}"
PORT="${COMFY3D_PORT:-8188}"
MODELS_DIR="${COMFY3D_MODELS_DIR:-/workspace/models/comfyui}"
OUTPUT_DIR="${COMFY3D_OUTPUT_DIR:-/workspace/output/comfyui}"
INPUT_DIR="${COMFY3D_INPUT_DIR:-/workspace/input}"

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
