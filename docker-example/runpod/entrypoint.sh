#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '[runpod-bootstrap] %s\n' "$*"
}

make_writable() {
  # RunPod persistent volumes can preserve ownership/modes across image updates.
  # Jupyter users need to be able to edit notebooks and write generated assets.
  # Keep this best-effort so read-only/special mounts do not prevent startup.
  for path in "$@"; do
    [ -e "$path" ] || continue
    chmod -R a+rwX "$path" 2>/dev/null || log "Could not chmod $path; continuing"
  done
}

link_dir() {
  local src="$1"
  local dst="$2"
  mkdir -p "$dst"
  if [ -d "$src" ] && [ ! -L "$src" ]; then
    shopt -s dotglob
    mv "$src"/* "$dst"/ 2>/dev/null || true
    shopt -u dotglob
    rm -rf "$src"
  fi
  ln -sfnT "$dst" "$src"
}

prepare_workspace() {
  local work="${WORKSPACE_ROOT:-/runpod-volume}"
  [ -d "${RUNPOD_VOLUME:-/runpod-volume}" ] && work="${RUNPOD_VOLUME:-/runpod-volume}"

  mkdir -p "$work"/{models,custom_nodes,manager,u2net,output,workflows,input,repos,notebooks,remesher}
  mkdir -p /root
  make_writable "$work/models" "$work/output" "$work/workflows" "$work/input" "$work/notebooks" "$work/remesher"

  rm -rf /root/.u2net || true
  ln -sfnT "$work/u2net" /root/.u2net
}

stage_demo_notebooks() {
  local work="${WORKSPACE_ROOT:-/workspace}"
  [ -d "${RUNPOD_VOLUME:-/workspace}" ] && work="${RUNPOD_VOLUME:-/workspace}"

  if [ -d /app/remesher ]; then
    mkdir -p "$work/remesher"
    cp -rn /app/remesher/. "$work/remesher/" 2>/dev/null || true
    if [ -d /app/remesher/workspace/input ]; then
      mkdir -p "$work/input"
      cp -rn /app/remesher/workspace/input/. "$work/input/" 2>/dev/null || true
    fi
    make_writable "$work/remesher" "$work/notebooks" "$work/input" "$work/output"
  fi
}

activate_venv() {
  if [ -f /app/.venv/bin/activate ]; then
    # shellcheck disable=SC1091
    source /app/.venv/bin/activate
  fi
}

setup_hermes_agent() {
  if [ "${HERMES_ENABLE:-1}" != "1" ]; then
    return
  fi

  if [ "${HERMES_INSTALL_ON_START:-1}" != "1" ]; then
    return
  fi

  local repo_url="${HERMES_REPO_URL:-https://github.com/NousResearch/hermes-agent.git}"
  local repo_dir="${HERMES_DIR:-/runpod-volume/hermes}"

  if [ ! -d "$repo_dir/.git" ]; then
    log "Cloning Hermes Agent into $repo_dir"
    mkdir -p "$(dirname "$repo_dir")"
    git clone "$repo_url" "$repo_dir"
  else
    log "Hermes repo already exists at $repo_dir"
  fi

  if [ -f "$repo_dir/pyproject.toml" ]; then
    log "Installing Hermes Agent"
    if command -v uv >/dev/null 2>&1; then
      (cd "$repo_dir" && uv pip install -e ".[cli,pty,mcp,cron]") || (cd "$repo_dir" && uv pip install -e .) || log "Hermes install via uv failed; continuing"
    elif command -v pip >/dev/null 2>&1; then
      (cd "$repo_dir" && pip install -e ".[cli,pty,mcp,cron]") || (cd "$repo_dir" && pip install -e .) || log "Hermes install via pip failed; continuing"
    fi
  fi
}

setup_remesher_cli() {
  if [ "${CLONE_REMESHER_ON_START:-1}" != "1" ]; then
    return
  fi

  local repo_url="${REMESHER_REPO_URL:-https://github.com/remesher/remesher.git}"
  local repo_dir="${REMESHER_DIR:-/runpod-volume/remesher}"

  if [ ! -d "$repo_dir/.git" ] && [ ! -f "$repo_dir/pyproject.toml" ]; then
    log "Cloning remesher CLI into $repo_dir"
    mkdir -p "$(dirname "$repo_dir")"
    git clone "$repo_url" "$repo_dir"
  else
    log "remesher repo already exists at $repo_dir"
  fi

  if [ -f "$repo_dir/pyproject.toml" ]; then
    log "Installing remesher CLI"
    if command -v uv >/dev/null 2>&1; then
      (cd "$repo_dir" && uv sync) || log "uv sync failed for remesher; continuing"
    elif command -v pip >/dev/null 2>&1; then
      (cd "$repo_dir" && pip install -e .) || log "pip install failed for remesher; continuing"
    fi
  fi

  if [ -f "$repo_dir/config.json.example" ]; then
    cp "$repo_dir/config.json.example" "$repo_dir/config.json" 2>/dev/null || true
  fi

  if [ -f "$repo_dir/config.json" ]; then
    sed -i 's#"server_url"[[:space:]]*:[[:space:]]*"[^"]*"#"server_url": "http://127.0.0.1:8188/"#' "$repo_dir/config.json" || true
  fi

  make_writable "$repo_dir"
}

run_model_download() {
  if [ "${DOWNLOAD_MODELS_ON_START:-1}" != "1" ]; then
    return
  fi

  log "Downloading model list into ${COMFY_MODELS_DIR:-/app/comfy/models}"
  python /app/runpod/download_models.py || log "Model downloader finished with warnings"
}

start_vlm() {
  if [ "${VLM_ENABLE:-1}" != "1" ]; then
    return
  fi

  local model_path="${VLM_MODEL_PATH:-}"
  if [ -z "$model_path" ]; then
    log "VLM enabled, but VLM_MODEL_PATH is empty; skipping"
    return
  fi

  if [ ! -f "$model_path" ]; then
    log "VLM model not found at $model_path; set VLM_MODEL_PATH or mount the model"
    return
  fi

  if [ -n "${VLM_SERVER_CMD:-}" ]; then
    log "Starting VLM using VLM_SERVER_CMD"
    bash -lc "${VLM_SERVER_CMD}" &
    PIDS+=("$!")
    return
  fi

  if command -v llama-server >/dev/null 2>&1; then
    log "Starting llama-server on :${VLM_PORT:-8080}"
    llama-server \
      -m "$model_path" \
      --host "${VLM_HOST:-0.0.0.0}" \
      --port "${VLM_PORT:-8080}" \
      --ctx-size "${VLM_CTX_SIZE:-8192}" \
      --n-gpu-layers "${VLM_N_GPU_LAYERS:-99}" &
    PIDS+=("$!")
    return
  fi

  log "Starting Python llama_cpp.server fallback on :${VLM_PORT:-8080}"
  python -m llama_cpp.server \
    --model "$model_path" \
    --host "${VLM_HOST:-0.0.0.0}" \
    --port "${VLM_PORT:-8080}" \
    --n_ctx "${VLM_CTX_SIZE:-8192}" &
  PIDS+=("$!")
}

start_hermes() {
  if [ "${HERMES_ENABLE:-1}" != "1" ]; then
    return
  fi

  export OPENAI_BASE_URL="${HERMES_MODEL_BASE_URL:-http://127.0.0.1:8080/v1}"
  export OPENAI_API_KEY="${HERMES_MODEL_API_KEY:-dummy}"

  if [ -n "${HERMES_START_COMMAND:-}" ]; then
    log "Starting Hermes with HERMES_START_COMMAND"
    if [ -d "${HERMES_DIR:-}" ]; then
      (cd "${HERMES_DIR}" && bash -lc "${HERMES_START_COMMAND}") &
    else
      bash -lc "${HERMES_START_COMMAND}" &
    fi
    PIDS+=("$!")
    return
  fi

  if command -v hermes >/dev/null 2>&1; then
    log "Starting Hermes (auto command)"
    hermes &
    PIDS+=("$!")
    return
  fi

  log "Hermes enabled but no command found. Set HERMES_START_COMMAND to your exact startup command."
}

setup_ollama() {
  if [ "${OLLAMA_PREP_ON_START:-0}" != "1" ]; then
    return
  fi

  local script="${REMESHER_DIR:-/workspace/remesher}/docker/demo-jupyter/scripts/ollama-gemma4.sh"
  if [ -x "$script" ] || [ -f "$script" ]; then
    log "Preparing Ollama model ${OLLAMA_MODEL:-gemma4}"
    bash "$script" || log "Ollama prep failed; continuing so Jupyter remains available"
  else
    log "Ollama prep requested, but $script was not found"
  fi
}

start_jupyter() {
  local work="${WORKSPACE_ROOT:-/runpod-volume}"
  export SHELL="${SHELL:-/bin/bash}"
  log "Starting JupyterLab from ${work} on :${JUPYTER_PORT:-8888}"
  jupyter lab \
    --ip=0.0.0.0 \
    --port "${JUPYTER_PORT:-8888}" \
    --no-browser \
    --allow-root \
    --ServerApp.disable_check_xsrf="${JUPYTER_DISABLE_XSRF:-1}" \
    --ServerApp.allow_origin="${JUPYTER_ALLOW_ORIGIN:-*}" \
    --ServerApp.allow_remote_access=True \
    --ServerApp.terminado_settings='{"shell_command":["/bin/bash"]}' \
    --NotebookApp.token="${JUPYTER_TOKEN:-}" \
    --ServerApp.token="${JUPYTER_TOKEN:-}" \
    --notebook-dir "${work}" &
  PIDS+=("$!")
}

cleanup() {
  log "Stopping background services"
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
}

trap cleanup EXIT SIGTERM SIGINT

PIDS=()
prepare_workspace
stage_demo_notebooks
activate_venv
setup_remesher_cli
run_model_download
start_vlm
setup_ollama
setup_hermes_agent
make_writable "${WORKSPACE_ROOT:-/runpod-volume}"/remesher "${WORKSPACE_ROOT:-/runpod-volume}"/input "${WORKSPACE_ROOT:-/runpod-volume}"/output "${WORKSPACE_ROOT:-/runpod-volume}"/notebooks
start_hermes
start_jupyter

if [ "${#PIDS[@]}" -eq 0 ]; then
  log "No services started; sleeping forever"
  tail -f /dev/null
fi

wait -n "${PIDS[@]}"
exit_code=$?
log "A service exited with code ${exit_code}; shutting down"
exit "$exit_code"
