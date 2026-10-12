#!/usr/bin/env bash
# One-shot setup: Python environment, model choice (llmfit), model server, quality check.
set -euo pipefail
cd "$(dirname "$0")"

command -v uv >/dev/null || { echo "Install uv first: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
[ -d .venv ] || uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt

PY=.venv/bin/python
$PY llm/pick.py "$@"
$PY llm/serve.py start
$PY llm/selfcheck.py || echo "The quality check failed. Pick a larger model: python llm/pick.py"

cat <<'EOF'

Next: start Open WebUI and register the tool.
  ./webui.sh                                  # in another terminal, http://127.0.0.1:3000
  .venv/bin/python openwebui/install.py       # after creating the admin account (add --api-key KEY)
EOF
