FROM nvidia/cuda:13.0.2-cudnn-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_PREFER_BINARY=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_NO_CACHE=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    ffmpeg \
    git \
    gnupg \
    jq \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    python3 \
    python3-pip \
    python3-venv \
    wget \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && . /etc/os-release \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli docker-buildx-plugin docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /app/.venv
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="/app/.venv/bin:$PATH"

RUN pip install --upgrade pip wheel setuptools && \
    pip install \
      docker \
      huggingface_hub \
      ipykernel \
      ipywidgets \
      jupyterlab \
      requests \
      uv

WORKDIR /app

COPY docker-example/runpod/entrypoint.sh /app/runpod/entrypoint.sh
COPY docker-example/runpod/download_models.py /app/runpod/download_models.py
COPY README.md pyproject.toml uv.lock config.json.example /app/remesher/
COPY src /app/remesher/src
COPY examples /app/remesher/examples
COPY notebooks /app/remesher/notebooks
COPY skills /app/remesher/skills
COPY docker/demo-jupyter/scripts /app/remesher/docker/demo-jupyter/scripts
COPY workspace/input/demo /app/remesher/workspace/input/demo

RUN chmod +x /app/runpod/entrypoint.sh /app/remesher/docker/demo-jupyter/scripts/*.sh && \
    uv pip install -e /app/remesher

ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility

ENV RUNPOD_VOLUME=/workspace
ENV WORKSPACE_ROOT=/workspace
ENV JUPYTER_PORT=8888
ENV COMFY_PORT=8188
ENV COMFY3D_IMAGE=michaelgold/comfy3d:latest
ENV COMFY3D_CONTAINER=comfy3d

ENV MODEL_CONFIG_URL=https://raw.githubusercontent.com/michaelgold/ComfyUI-HF-Model-Downloader/main/model_config.json
ENV DOWNLOAD_MODELS_ON_START=0
ENV ALLOW_PROTECTED_MODELS=0
ENV SKIP_EXISTING_MODELS=1
ENV COMFY_MODELS_DIR=/runpod-volume/models

ENV CLONE_REMESHER_ON_START=1
ENV REMESHER_REPO_URL=https://github.com/remesher/remesher.git
ENV REMESHER_DIR=/workspace/remesher

ENV OLLAMA_PREP_ON_START=0
ENV OLLAMA_MODEL=gemma4

ENV VLM_ENABLE=0
ENV VLM_HOST=0.0.0.0
ENV VLM_PORT=8080
ENV VLM_MODEL_PATH=/runpod-volume/models/vlm/gemma-4-e4b-it-gguf/gemma-4-e4b-it-Q4_K_M.gguf
ENV VLM_CTX_SIZE=8192
ENV VLM_N_GPU_LAYERS=99
ENV VLM_SERVER_CMD=

ENV HERMES_ENABLE=0
ENV HERMES_INSTALL_ON_START=1
ENV HERMES_REPO_URL=https://github.com/NousResearch/hermes-agent.git
ENV HERMES_DIR=/runpod-volume/hermes
ENV HERMES_START_COMMAND=
ENV HERMES_MODEL_BASE_URL=http://127.0.0.1:8080/v1

EXPOSE 8888 8188 8080

ENTRYPOINT ["/app/runpod/entrypoint.sh"]
