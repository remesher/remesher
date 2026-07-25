# Remesher Jupyter demo container

Build and run on the GPU host from the Remesher repo root:

```bash
docker compose -f docker-compose.demo-jupyter.yml up --build
```

Open:

```text
http://<host>:8888/lab?token=remesher
```

Shared folders:

- `workspace/input/` uploads from host/Jupyter
- `workspace/output/` downloads from host/Jupyter
- `workspace/models/` persistent model cache area

Notebook 01 starts `michaelgold/comfy3d` through the mounted Docker socket and runs `comfy-prompt-cli`.
Notebook 02 starts Ollama, pulls `${OLLAMA_MODEL:-gemma4}`, and prepares pi.dev to use `skills/remesher-cli/SKILL.md`.
