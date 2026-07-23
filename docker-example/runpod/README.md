# RunPod Single-Image Template

This folder provides a RunPod-friendly, single Docker image setup (no docker-compose) that:

- Starts Comfy3D (`michaelgold/comfy3d`) on port `8188`
- Starts a Gemma 4 backend on port `8080` (llama.cpp binary if available, otherwise `llama-cpp-python` server)
- Clones and installs `github.com/remesher/remesher` so Hermes can call the remesher CLI
- Clones and installs Hermes Agent from `https://github.com/NousResearch/hermes-agent` on startup
- Starts Hermes with either your command (`HERMES_START_COMMAND`) or the default `hermes`
- Downloads models from:
  - `https://github.com/michaelgold/ComfyUI-HF-Model-Downloader/blob/main/model_config.json`
  into the persistent RunPod volume-backed models directory

## Build

```bash
docker build -t remesher-runpod -f docker-example/runpod/Dockerfile docker-example/runpod
```

## Run (local example)

```bash
docker run --gpus all --rm -it \
  -p 8188:8188 \
  -p 8080:8080 \
  -e HERMES_START_COMMAND="<your hermes startup command>" \
  -e VLM_MODEL_PATH="/runpod-volume/models/vlm/gemma-4-e4b-it-gguf/gemma-4-e4b-it-Q4_K_M.gguf" \
  -v /path/to/runpod-volume:/runpod-volume \
  remesher-runpod
```

## Important Env Vars

- `HERMES_INSTALL_ON_START`: Defaults to `1`; set `0` to skip Hermes clone/install.
- `HERMES_REPO_URL`: Defaults to `https://github.com/NousResearch/hermes-agent.git`.
- `HERMES_DIR`: Defaults to `/runpod-volume/hermes`.
- `HERMES_START_COMMAND`: Optional. If unset, the entrypoint runs `hermes`.
- `HERMES_MODEL_BASE_URL`: Defaults to `http://127.0.0.1:8080/v1`.
- `HERMES_MODEL_API_KEY`: Defaults to `dummy`.
- `VLM_MODEL_PATH`: Path to your Gemma 4 GGUF model.
- `MODEL_CONFIG_URL`: Defaults to the upstream `model_config.json` URL.
- `ALLOW_PROTECTED_MODELS`: `0` by default. Set to `1` only if you accept/download protected models and have valid HF auth.
- `COMFY_MODELS_DIR`: Defaults to `/app/comfy/models` (symlinked to volume-backed storage).

## Notes

- This image is intentionally a bootstrap wrapper around `michaelgold/comfy3d:latest`.
- Hermes is installed from source at pod startup with `pip/uv pip install -e` in `HERMES_DIR`.
- If your preferred Hermes run mode needs extra flags (for example gateway mode), set `HERMES_START_COMMAND`.
- For private/protected Hugging Face models, provide `HF_TOKEN` in the pod environment.
