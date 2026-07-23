FROM michaelgold/comfy3d:latest

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Extra runtime helpers for model download + optional llama-cpp Python server fallback.
RUN /app/.venv/bin/pip install --no-cache-dir \
    huggingface_hub \
    requests \
    llama-cpp-python

WORKDIR /app

COPY entrypoint.sh /app/runpod/entrypoint.sh
COPY download_models.py /app/runpod/download_models.py

RUN chmod +x /app/runpod/entrypoint.sh

ENV RUNPOD_VOLUME=/runpod-volume
ENV WORKSPACE_ROOT=/runpod-volume
ENV COMFY_MODELS_DIR=/app/comfy/models
ENV COMFY_PORT=8188

ENV MODEL_CONFIG_URL=https://raw.githubusercontent.com/michaelgold/ComfyUI-HF-Model-Downloader/main/model_config.json
ENV DOWNLOAD_MODELS_ON_START=1
ENV ALLOW_PROTECTED_MODELS=0
ENV SKIP_EXISTING_MODELS=1

ENV CLONE_REMESHER_ON_START=1
ENV REMESHER_REPO_URL=https://github.com/remesher/remesher.git
ENV REMESHER_DIR=/runpod-volume/remesher

ENV VLM_ENABLE=1
ENV VLM_HOST=0.0.0.0
ENV VLM_PORT=8080
ENV VLM_MODEL_PATH=/runpod-volume/models/vlm/gemma-4-e4b-it-gguf/gemma-4-e4b-it-Q4_K_M.gguf
ENV VLM_CTX_SIZE=8192
ENV VLM_N_GPU_LAYERS=99
ENV VLM_SERVER_CMD=

ENV HERMES_ENABLE=1
ENV HERMES_INSTALL_ON_START=1
ENV HERMES_REPO_URL=https://github.com/NousResearch/hermes-agent.git
ENV HERMES_DIR=/runpod-volume/hermes
ENV HERMES_START_COMMAND=
ENV HERMES_MODEL_BASE_URL=http://127.0.0.1:8080/v1

EXPOSE 8188 8080

ENTRYPOINT ["/app/runpod/entrypoint.sh"]
