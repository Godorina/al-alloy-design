# Windows(PowerShell)용 한 번에 설치: setup.sh 와 같은 일을 합니다.
#   .\setup.ps1 --repo unsloth/Qwen3.8-27B-GGUF --quant Q4_K_M
# 막히면 먼저 한 번 실행: Set-ExecutionPolicy -Scope Process Bypass
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:PYTHONUTF8 = "1"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "먼저 uv를 설치하세요: https://docs.astral.sh/uv/getting-started/installation/"; exit 1
}
if (-not (Test-Path .venv)) { uv venv --python 3.12 .venv }
$py = ".venv\Scripts\python.exe"
uv pip install --python $py -r requirements.txt

& $py llm/pick.py @args
& $py llm/serve.py start
& $py llm/selfcheck.py
if ($LASTEXITCODE -ne 0) { Write-Host "품질 점검에 실패했습니다. 더 큰 모델을 고르세요: $py llm/pick.py" }

Write-Host @"

설치가 끝났습니다. 다음으로 설계를 실행하세요 (새 PowerShell 마다 먼저 `$env:PYTHONUTF8 = "1"):
  $py design.py "6xxx T6 압출, UTS 330 MPa 이상, 연신율 10% 이상, 내식성 좋게"
자세한 사용법은 README.md 를 보세요.
"@
