# Remesher RunPod / Jupyter Docker Image

This folder defines the Docker image published as `michaelgold/remesher`.

The image is a **Remesher notebook/control environment**, not the Comfy3D runtime itself:

- Builds from `nvidia/cuda:13.0.2-cudnn-runtime-ubuntu24.04`
- Starts JupyterLab on port `8888`
- Stages the Remesher demo notebooks into `/workspace/remesher/notebooks`
- Stages helper scripts under `/workspace/remesher/docker/demo-jupyter/scripts`
- Installs the Remesher CLI into the image venv
- Includes the Docker CLI/Python Docker SDK so notebooks can pull and run `michaelgold/comfy3d`
- Includes Ollama/Gemma4 prep scripts for notebook 04

The notebooks intentionally start/pull the Comfy3D container themselves, for example via:

```bash
bash docker/demo-jupyter/scripts/pull-comfy3d.sh
```

## Local smoke run

```bash
docker build -t michaelgold/remesher:local -f docker-example/runpod/Dockerfile .

docker run --gpus all --rm -it \
  -p 8888:8888 \
  -p 8188:8188 \
  -p 8080:8080 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$PWD/workspace:/workspace" \
  michaelgold/remesher:local
```

Open Jupyter and run:

```text
/workspace/remesher/notebooks/01_comfy3d_remesher_cli.ipynb
```

## Important runtime mount

For the notebook to pull/run `michaelgold/comfy3d`, the container needs access to the host Docker socket:

```text
-v /var/run/docker.sock:/var/run/docker.sock
```

RunPod templates should expose that socket or use an equivalent Docker-in-Docker/control-plane setup.

The image includes the Docker CLI, and CI verifies the client is installed. The common RunPod failure is not a missing
`docker` binary; it is a missing Docker daemon/socket, for example:

```text
failed to connect to the docker API at unix:///var/run/docker.sock: no such file or directory
```

If your RunPod template cannot expose `/var/run/docker.sock`, start Comfy3D separately and point the notebooks at it:

```bash
export COMFY3D_SERVER_URL="https://<your-comfy3d-endpoint>/"
bash docker/demo-jupyter/scripts/pull-comfy3d.sh
```

When `COMFY3D_SERVER_URL` or `COMFYUI_SERVER_URL` is set, `pull-comfy3d.sh` health-checks that endpoint, writes it to
`config.json`, and skips Docker.

## Ollama / Gemma4

Notebook 04 uses:

```bash
bash docker/demo-jupyter/scripts/ollama-gemma4.sh
```

By default, the container does **not** pull Gemma4 at startup. To preinstall it on boot:

```bash
-e OLLAMA_PREP_ON_START=1 -e OLLAMA_MODEL=gemma4
```

## Environment defaults

| Variable | Default |
| --- | --- |
| `WORKSPACE_ROOT` | `/workspace` |
| `JUPYTER_PORT` | `8888` |
| `JUPYTER_TOKEN` | unset; may be passed at runtime |
| `COMFY3D_IMAGE` | `michaelgold/comfy3d:latest` |
| `COMFY3D_CONTAINER` | `comfy3d` |
| `COMFY3D_SERVER_URL` | unset; use an already-running Comfy3D/ComfyUI endpoint instead of Docker |
| `OLLAMA_PREP_ON_START` | `0` |
| `OLLAMA_MODEL` | `gemma4` |

## Notes

- This image intentionally does not inherit from `michaelgold/comfy3d`.
- Comfy3D is pulled/run by the notebooks so it can remain separately versioned and cached.
- Protected Hugging Face downloads still require `HF_TOKEN` in the notebook/session environment.
