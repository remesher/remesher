FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_PROJECT_ENVIRONMENT=/opt/remesher-venv \
    PATH="/opt/remesher-venv/bin:/root/.local/bin:/usr/local/bin:${PATH}"

RUN apt-get update && apt-get install -y --no-install-recommends \
      bash ca-certificates curl git gnupg jq procps unzip xz-utils zstd docker.io \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && node --version \
    && npm --version \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --upgrade pip \
    && python -m pip install uv notebook jupyterlab ipywidgets huggingface_hub requests pillow tqdm rich

WORKDIR /workspace/remesher

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY examples ./examples
COPY config.json.example ./config.json.example
COPY skills ./skills
COPY notebooks ./notebooks
COPY docker/demo-jupyter/scripts ./docker/demo-jupyter/scripts

RUN uv sync --frozen \
    && ln -sf /opt/remesher-venv/bin/comfy-prompt-cli /usr/local/bin/comfy-prompt-cli
RUN mkdir -p /workspace/input /workspace/output /workspace/models /workspace/notebooks \
    && cp -R notebooks/* /workspace/notebooks/

EXPOSE 8888 11434
CMD ["bash", "docker/demo-jupyter/scripts/start-jupyter.sh"]
