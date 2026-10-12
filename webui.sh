#!/usr/bin/env bash
# Start Open WebUI with its data kept inside this folder (.webui/).
set -euo pipefail
cd "$(dirname "$0")"
export DATA_DIR="$PWD/.webui"
export ENABLE_OLLAMA_API=False
exec uvx --python 3.12 open-webui@latest serve --host 127.0.0.1 --port "${WEBUI_PORT:-3000}"
