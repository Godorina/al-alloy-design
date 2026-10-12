#!/usr/bin/env bash
# 한 번에 설치: 파이썬 환경, 모델 선택(llmfit), 모델 서버, 품질 점검.
set -euo pipefail
cd "$(dirname "$0")"

command -v uv >/dev/null || { echo "먼저 uv를 설치하세요: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
[ -d .venv ] || uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt

PY=.venv/bin/python
$PY llm/pick.py "$@"
$PY llm/serve.py start
$PY llm/selfcheck.py || echo "품질 점검에 실패했습니다. 더 큰 모델을 고르세요: .venv/bin/python llm/pick.py"

cat <<'EOF'

설치가 끝났습니다. 다음으로 설계를 실행하세요:
  .venv/bin/python design.py "6xxx T6 압출, UTS 330 MPa 이상, 연신율 10% 이상, 내식성 좋게"
자세한 사용법은 README.md 를 보세요. (Open WebUI를 쓰려면 docs/webui.md)
EOF
