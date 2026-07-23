#!/usr/bin/env bash
set -euo pipefail
cd /workspace/remesher
export PATH=/opt/remesher-venv/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin
if [[ ! -f config.json ]]; then cp config.json.example config.json; fi
echo "Remesher Jupyter demo"
echo "- Remesher repo: /workspace/remesher"
echo "- Shared input:  /workspace/input"
echo "- Shared output: /workspace/output"
echo "- Notebooks:     /workspace/notebooks"
echo "- Token:         ${JUPYTER_TOKEN:-remesher}"
exec jupyter lab --ip=0.0.0.0 --port=8888 --no-browser --allow-root \
  --NotebookApp.token="${JUPYTER_TOKEN:-remesher}" \
  --ServerApp.root_dir=/workspace
