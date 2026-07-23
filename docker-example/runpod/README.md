# Remesher RunPod / Jupyter Docker Image

This folder defines the Docker image published as `michaelgold/remesher`.

The RunPod image is a **combined Remesher + Comfy3D notebook environment**:

- Builds from `michaelgold/comfy3d:latest`
- Starts ComfyUI/Comfy3D inside the same container on port `8188`
- Starts JupyterLab on port `8888`
- Stages the Remesher demo notebooks into `/workspace/remesher/notebooks`
- Stages helper scripts under `/workspace/remesher/docker/demo-jupyter/scripts`
- Installs the Remesher CLI into the image venv
- Includes Ollama/Gemma4 prep scripts for notebook 04

The notebooks no longer require a Docker socket on RunPod. The setup cell:

```bash
bash docker/demo-jupyter/scripts/pull-comfy3d.sh
```

now waits for the in-container ComfyUI endpoint and writes `config.json` with:

```json
{"server_url": "http://127.0.0.1:8188/"}
```

## Local smoke run

```bash
docker build -t michaelgold/remesher:local -f docker-example/runpod/Dockerfile .

docker run --gpus all --rm -it \
  -p 8888:8888 \
  -p 8188:8188 \
  -p 8080:8080 \
  -v "$PWD/workspace:/workspace" \
  michaelgold/remesher:local
```

Open Jupyter and run:

```text
/workspace/remesher/notebooks/01_comfy3d_remesher_cli.ipynb
```

## Comfy3D endpoint behavior

Default RunPod behavior is in-container ComfyUI:

```text
http://127.0.0.1:8188/
```

If you want to use a separate Comfy3D/ComfyUI service instead, set one of:

```bash
export COMFY3D_SERVER_URL="https://<your-comfy3d-endpoint>/"
export COMFYUI_SERVER_URL="https://<your-comfy3d-endpoint>/"
```

Then rerun:

```bash
bash docker/demo-jupyter/scripts/pull-comfy3d.sh
```

The script health-checks `${URL}/system_stats`, writes the URL to `config.json`, and skips local Docker/sibling-container behavior.

## Docker socket fallback

Older/local control-image deployments may still use `pull-comfy3d.sh` to launch a sibling `michaelgold/comfy3d` container through Docker. That path still exists as a fallback, but the RunPod image should not need it.

For that legacy path only, Docker daemon access requires:

```text
-v /var/run/docker.sock:/var/run/docker.sock
```

The common failure:

```text
failed to connect to the docker API at unix:///var/run/docker.sock: no such file or directory
```

means the Docker CLI is installed but the daemon/socket is unavailable. Recreate with the current combined `michaelgold/remesher` image instead of trying to mount Docker on RunPod when possible.

## Ollama / Gemma4

Notebook 04 uses:

```bash
bash docker/demo-jupyter/scripts/ollama-gemma4.sh
```

Ollama/Gemma runs directly inside the container; it does **not** require Docker. By default, the container does not pull Gemma4 at startup. To preinstall it on boot:

```bash
-e OLLAMA_PREP_ON_START=1 -e OLLAMA_MODEL=gemma4
```

## Environment defaults

| Variable | Default |
| --- | --- |
| `WORKSPACE_ROOT` | `/workspace` |
| `JUPYTER_PORT` | `8888` |
| `JUPYTER_TOKEN` | unset; may be passed at runtime |
| `COMFY_PORT` | `8188` |
| `COMFY3D_SERVER_URL` | `http://127.0.0.1:8188/` |
| `RUNPOD_COMBINED_COMFY3D` | `1` |
| `COMFY3D_START_ON_BOOT` | `1` |
| `OLLAMA_PREP_ON_START` | `0` |
| `OLLAMA_MODEL` | `gemma4` |

## Notes

- Protected Hugging Face downloads still require `HF_TOKEN` in the notebook/session environment.
- `/workspace/models`, `/workspace/input`, `/workspace/output`, and `/workspace/custom_nodes` are persistent/writable when backed by a RunPod volume.
