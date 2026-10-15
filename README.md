# Al Alloy Design — 알루미늄 합금 역설계 (CLI)

로컬 LLM과 실측 데이터로 "원하는 물성의 알루미늄 합금 조성"을 찾아 주는 도구입니다.
이 브랜치(`windows-support`)의 `bootstrap.py` 는 **Windows / WSL / Linux / macOS 를 스스로 감지**해서 그 환경에 맞게 설치합니다. 터미널 명령(CLI)으로 실행합니다.

## 빠른 설치 (명령어)

**WSL(Ubuntu) / Linux 안에서** — 터미널에 차례로 입력합니다. GPU(NVIDIA)·CPU 를 감지해서 맞게 빌드하고, 메모리/VRAM 에 맞는 모델을 받습니다.

```bash
git clone -b windows-support https://github.com/Godorina/al-alloy-design.git ~/al-alloy-design
cd ~/al-alloy-design
python3 bootstrap.py --yes
```

**WSL 이 아직 없는 Windows** — PowerShell 에서. WSL·Ubuntu 설치부터 위 단계까지 한 번에 합니다.

```powershell
cd $HOME\Downloads
irm https://raw.githubusercontent.com/Godorina/al-alloy-design/windows-support/install-wsl.ps1 -OutFile install-wsl.ps1
powershell -ExecutionPolicy Bypass -File .\install-wsl.ps1
```

- `-b windows-support` 를 꼭 붙이세요. 기본 브랜치(`main`)에는 이 설치 기능이 없습니다.
- 설치가 끝나면 터미널을 새로 열고: `cd ~/al-alloy-design && .venv/bin/python design.py -v "6xxx T6 압출, UTS 330 MPa 이상, 연신율 10% 이상"`
- 단계별 화면, GPU/CPU 차이, 문제 해결: **[docs/install-windows.md](docs/install-windows.md)**

```
요구사항(문장)
   │  design.py
   ▼
모델 서버(llama-server) ◄── llmfit 이 내 PC 에 맞는 모델을 추천·다운로드
   │  모델이 스킬을 읽고 도구를 호출
   ▼
① examples.py   실측 합금 예시 조회
② score.py      후보 조성 채점 (ICL + CatBoost 강도, 연신율, 밀도, 부식 규칙)
③ corrosion.py  지식그래프(KG)에서 부식 근거 첨부
   ▼
후보표 + 가정 + 한계  →  화면 출력 + results/날짜.md 저장
```

## 0. 먼저 알아둘 것

| 항목 | 내용 |
|---|---|
| 지원 환경 | Windows 10/11(PowerShell 7 권장: `winget install Microsoft.PowerShell`), WSL2 의 Linux, Linux, macOS. `bootstrap.py` 가 감지합니다. WSL 이 없는 Windows 는 `install-wsl.ps1` 이 WSL 부터 만들어 줍니다 (1.0). **Windows 11 Home + WSL2(Ubuntu 26.04), CPU 로 설치·설계 루프까지 확인했습니다. NVIDIA GPU(CUDA) 경로와 네이티브 Windows 는 아직 실제로 시험하지 못했습니다.** 막히면 오류 메시지를 알려 주세요 |
| 한글 깨짐 방지 | 새 PowerShell 마다 `$env:PYTHONUTF8 = "1"` (영구 적용: `setx PYTHONUTF8 1` 후 새 창). `bootstrap.py` 는 자동으로 설정합니다 |
| 명령 표기 | 이 README 의 `.venv\Scripts\python.exe` 는 WSL/Linux/macOS 에서는 `.venv/bin/python` 으로 읽으세요 |
| 결과의 성격 | 강도(UTS/YTS)·연신율은 **예측값**입니다. 부식은 예측하지 않고 **가장 가까운 합금의 실측·공칭 값**을 보여 줍니다 |
| 모델 크기 | 모델이 작으면 설계 루프가 끝까지 돌지 않을 수 있습니다 (아래 2.5, 5장) |

## 1. 준비물

### 1.0 Windows 에서 WSL 부터 한 번에 (install-wsl.ps1)

WSL 이 없는 Windows PC 는 PowerShell 명령 세 줄이면 됩니다 (맨 위 "빠른 설치"와 같음). git 도 파이썬도 WSL 도 미리 없어도 되고, WSL 이 이미 있으면 끝난 단계는 건너뜁니다.

```powershell
cd $HOME\Downloads
irm https://raw.githubusercontent.com/Godorina/al-alloy-design/windows-support/install-wsl.ps1 -OutFile install-wsl.ps1
powershell -ExecutionPolicy Bypass -File .\install-wsl.ps1          # 옵션 예: -User alloy -Yes
```

묻는 것은 이것뿐입니다: 관리자 권한 창(`예`), 재부팅(필요할 때만), 리눅스 사용자 이름과 비밀번호. 나머지(빌드, 모델 다운로드, 점검)는 자동으로 끝까지 진행됩니다 (보통 30분~1시간).
(명령어 대신 ZIP 을 받았다면 압축을 푼 폴더의 `install.cmd` 를 실행해도 같습니다.)

| 단계 | 하는 일 |
|---|---|
| 1. 사전 점검 | Windows 빌드(19041 이상), 가상화, 디스크, 메모리, **GPU**: NVIDIA + 드라이버가 CUDA 13.2 이상이면 GPU 로, NVIDIA 가 아니면 CPU 로. NVIDIA 인데 드라이버가 없거나 오래됐으면 "CPU 로 계속 / 드라이버 페이지 열고 멈춤" 을 물어봅니다 |
| 2. Windows 기능 | WSL, 가상 머신 플랫폼을 켭니다 (관리자 권한 창에서 `예`). 재부팅이 필요하면 `shutdown /r` 로 재부팅하고, 로그인하면 **자동으로 이어서** 실행됩니다 |
| 3. 배포판 | Ubuntu 를 설치합니다 |
| 4. 사용자 | 리눅스 계정을 만들고 기본 사용자로 지정합니다. **비밀번호만 직접 입력**합니다 |
| 5. 메모리 | `%UserProfile%\.wslconfig` 의 `memory` 를 RAM 의 약 65% 로 맞춥니다 (WSL 기본값은 50%) |
| 6. 프로젝트 | WSL 안에서 apt 패키지 → `git clone` (`~/al-alloy-design`) → (NVIDIA 면) CUDA 빌드 도구 → `python3 bootstrap.py --yes` |

- 끝나면 **요약**이 나옵니다: 계산 장치(실제로 GPU 를 잡았는지 `llama-server --list-devices` 로 확인), 모델, 모델 서버 상태.
- 재부팅은 이번 실행에서 WSL 기능을 켰을 때만 합니다. Windows 업데이트 때문에 생긴 재부팅 대기는 건드리지 않습니다.
- 이미 끝난 단계는 건너뛰므로 중간에 멈춰도 같은 명령을 다시 실행하면 됩니다.
- 실제 설치 위치는 WSL 안의 `~/al-alloy-design` 입니다 (Windows 폴더보다 훨씬 빠름). 받은 `install-wsl.ps1` 은 설치 뒤 지워도 됩니다. 로그: `%LOCALAPPDATA%\al-alloy-design\install-wsl.log`
- 옵션: `-User 이름`, `-MemoryGB 20`, `-ModelRepo unsloth/Qwen3-14B-GGUF`, `-Quant Q4_K_M`, `-SkipBootstrap`(WSL 준비와 clone 까지만), `-NoExisting`(이미 있는 모델을 쓰지 않고 새로 다운로드), `-Yes`(묻지 않음, 재부팅 포함)
- 끝나면 시작 메뉴의 **Ubuntu** 를 열고 `cd ~/al-alloy-design` 후 3장으로 가세요. WSL 안에서는 `.venv\Scripts\python.exe` 대신 `.venv/bin/python`, `python` 대신 `python3` 입니다.

### 1.1 도구 설치

`bootstrap.py`(2.2)가 빠진 도구를 감지해서 설치해 줍니다. 직접 설치하려면 아래 표를 따르세요 (Windows 기준; WSL/Linux 는 `apt install git curl cmake build-essential` 과 uv 설치 스크립트, llama.cpp 는 소스 빌드).

| 도구 | 용도 | 설치 명령 |
|---|---|---|
| git | 저장소 내려받기 | `winget install Git.Git` |
| uv | 파이썬 환경 | `winget install astral-sh.uv` (설치 후 새 터미널) |
| llama.cpp | 모델 서버(`llama-server`) | `winget install --id ggml.llamacpp` (못 찾으면 `winget search llama.cpp` 또는 <https://github.com/ggml-org/llama.cpp/releases> 의 Windows 빌드: NVIDIA 는 CUDA, 그 외는 Vulkan) |
| llmfit | 내 PC 에 맞는 모델 추천 | 따로 설치하지 않아도 됩니다. 2.2 단계에서 없으면 설치할지 물어봅니다 (`scoop install llmfit` 또는 `uv tool install llmfit`) |

설치 확인:

```powershell
git --version; uv --version; llama-server --version
```

### 1.2 여유 공간과 메모리

- 디스크: 모델 2~20GB(고른 모델에 따라) + 파이썬 환경 약 600MB
- 메모리: llmfit 이 내 PC 의 메모리에 들어가는 모델만 추천합니다. 원 저장소를 만들 때 시험한 PC 는 메모리 48GB 의 Apple Silicon Mac 이었고, 윈도우 사양에서는 확인하지 않았습니다. NVIDIA GPU 가 있으면 VRAM 에 들어가는 모델이 훨씬 빠릅니다

## 2. 설치 (처음 한 번)

### 2.1 저장소 내려받기

```powershell
git clone -b windows-support https://github.com/Godorina/al-alloy-design.git
cd al-alloy-design
```


### 2.2 한 번에 설치

먼저 이 PC 를 감지해 결과와 "할 일"을 보여 주고, 확인(`Y`)하면 진행합니다.

```powershell
python bootstrap.py                    # Windows 에 python 이 없으면: winget install astral-sh.uv 후 uv run bootstrap.py
python bootstrap.py --detect-only      # 감지 결과만 보기
python bootstrap.py --yes              # 묻지 않고 진행
python bootstrap.py --no-existing      # 이미 있는 모델(Ollama 등)을 쓰지 않고 새로 다운로드
```

감지하는 것과 그에 따른 동작:

| 감지 | 동작 |
|---|---|
| 환경 (Windows / WSL1·2 / Linux / macOS) | 환경에 맞는 설치 방법을 고름 (winget / apt + 소스 빌드 / brew). WSL1 이면 경고, `/mnt/` 아래이면 느리다고 경고 |
| NVIDIA GPU, VRAM | 있으면 VRAM 을, 없으면 메모리의 60% 를 "모델 예산"으로 계산. WSL 에서 `nvcc` 가 없으면 `scripts/install-cuda-wsl.sh` 로 NVIDIA 의 WSL 전용 저장소에서 빌드 도구만(nvcc, cuBLAS 약 1GB) 설치 — 드라이버는 설치하지 않음, 버전은 Windows 드라이버가 지원하는 범위에서 고름. 그다음 CUDA 로 빌드하고, 이미 CPU 로 빌드돼 있으면 다시 빌드. 일반 Linux 는 `nvcc` 가 있을 때만 CUDA. Intel/AMD 내장 GPU 는 쓰지 않음 (CPU) |
| 메모리 | 예산이 24GB 이상이면 Qwen3.8-27B(약 15GB + 컨텍스트), 10~24GB 면 Qwen3-14B(`unsloth/Qwen3-14B-GGUF`, 약 9GB), 그보다 작으면 llmfit 이 이 PC 에 맞다고 고른 1순위 모델을 묻지 않고 받음 (직접 고르려면 `python llm/pick.py` 를 따로 실행). 모델 서버 동시 요청 수는 24GB 미만이면 1, 이상이면 2 (`--slots` 로 지정) |
| 이미 받아 둔 모델 | Ollama, LM Studio, Hugging Face/llama.cpp 캐시의 GGUF 파일을 찾습니다 (WSL 이면 Windows 쪽 `C:\Users\*` 도). 도구 호출 템플릿이 있고 7B 이상이며 모델 예산에 들어가는 것이 있으면 **다운로드 대신 그 파일을 이 프로젝트의 llama-server 로 실행** (아래 "이미 있는 모델 쓰기") |
| 설치된 도구 | git, uv, llama-server, llmfit 중 없는 것만 설치. Windows 는 설치 후 PATH 갱신을 위해 새 PowerShell 에서 같은 명령을 다시 실행해야 함 |

모델을 직접 지정하려면 옵션을 그대로 붙입니다 (나머지 옵션은 `llm/pick.py` 로 전달됩니다).

```powershell
python bootstrap.py --repo unsloth/Qwen3.8-27B-GGUF --quant Q4_K_M
```

- `--repo` 는 Hugging Face 의 GGUF 저장소를 직접 지정하는 옵션입니다 (이 모델은 llmfit 순위 목록에 나오지 않습니다).
- `--quant Q4_K_M` 은 모델을 4비트 양자화로 받는 옵션입니다. 이 저장소에서는 `Qwen3.8-27B-UD-Q4_K_M.gguf` 한 파일이 선택됩니다.

가벼운 모델로 먼저 시험해 보려면 (설계 루프는 끝까지 돌지 않는 경우가 많습니다, 2.5 참고):

```powershell
python bootstrap.py --quant Q4_K_M       # llmfit 순위에서 번호 선택 (예: Qwen3-4B)
```

#### 이미 있는 모델 쓰기

Ollama, LM Studio 등으로 받아 둔 모델이 있으면 `bootstrap.py` 가 감지 결과 아래에 보여 줍니다.

```
  기존 모델 3개 발견, 그중 쓸 수 있는 것 1개
    O qwen3:14b (Ollama, 14B Q4_K_M, 8.6GB)
    - llama3.2:3b (Ollama, 3B Q4_K_M, 1.9GB)  [너무 작음 (약 3B, 7B 이상 필요)]
```

- 쓸 수 있는(`O`) 모델이 있으면 번호를 묻고(`--yes` 면 가장 큰 것), 다운로드 대신 그 파일을 씁니다. `0` 을 고르거나 `--no-existing` 을 붙이면 원래대로 권장 모델을 받습니다.
- Ollama/LM Studio 서버에 접속하는 것이 아니라 **모델 파일만** 빌려 와서 이 프로젝트의 llama-server 로 켭니다. 그래서 컨텍스트 길이, 도구 호출 형식, 생각(thinking) 끄기 설정이 권장 모델과 같게 적용됩니다. Ollama 가 같은 모델을 켜 두고 있으면 메모리를 두 배로 쓰니 `ollama stop 이름` 으로 내려 두세요.
- WSL 에서 Windows 쪽 모델을 쓸 때는 한 번 `models/` 로 복사합니다 (Windows 드라이브에서 직접 읽으면 켤 때마다 매우 느림).
- 그 파일로 서버가 켜지지 않으면(일부 Ollama 전용 형식) 자동으로 권장 모델을 받아서 다시 켭니다.
- 이미 모델을 골라 둔 경우(`.llm/selection.json` 이 있음)나 `--repo` 등으로 직접 지정한 경우에는 찾지 않습니다. 다른 폴더도 찾으려면 `--search 폴더`, 찾은 목록만 보려면 `python llm/existing.py`.

실행되는 일은 4단계입니다. `--repo` 없이 실행하면 중간에 "Download which one? [1]" 이 나오고, 순위표의 번호를 입력합니다.

| 순서 | 하는 일 | 걸리는 시간 |
|---|---|---|
| 1 | `.venv` 만들고 `requirements.txt` 설치 | 1~2분 |
| 2 | llmfit 이 내 PC 사양으로 모델 순위를 보여 주고, 고른 모델을 `models/` 에 다운로드 | 모델 크기에 따라 |
| 3 | `llama-server` 를 켜고 `.env` 에 접속 정보를 기록 | 약 10초~1분 |
| 4 | 품질 점검(`selfcheck`): 도구 호출, 강도 예측 오차 | 1~2분 |

끝나면 `PASS` 또는 `WARN`/`FAIL` 한 줄이 나옵니다 (의미는 2.4).

### 2.3 단계별로 직접 하기 (bootstrap.py 를 쓰지 않을 때)

```powershell
# (1) 파이썬 환경
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt

# (2) 모델 고르기 + 다운로드
.venv\Scripts\python.exe llm/pick.py --list-only            # 순위만 보기
.venv\Scripts\python.exe llm/pick.py --quant Q4_K_M         # 번호를 골라 다운로드
.venv\Scripts\python.exe llm/pick.py --auto --quant Q4_K_M  # 묻지 않고 1순위 다운로드 (1순위는 큰 모델일 수 있으니 순위부터 확인)
.venv\Scripts\python.exe llm/pick.py --repo unsloth/Qwen3.8-27B-GGUF --quant Q4_K_M   # 권장: Qwen3.8-27B 직접 지정 (약 15GB)
.venv\Scripts\python.exe llm/existing.py                    # 이 PC 에 이미 있는 모델 찾기 (Ollama, LM Studio 등)
.venv\Scripts\python.exe llm/pick.py --gguf 파일경로          # 다운로드 대신 이미 있는 GGUF 파일 쓰기 (--copy: models/ 로 복사)

# (3) 모델 서버 켜기 (.env 가 자동으로 만들어짐)
.venv\Scripts\python.exe llm/serve.py start

# (4) 품질 점검
.venv\Scripts\python.exe llm/selfcheck.py                   # 도구 호출 + 강도 예측 (1~2분)
.venv\Scripts\python.exe llm/selfcheck.py --agent           # 설계 전체 한 번 실행 (5~10분)
```

`pick.py` 옵션: `--list-only`(순위만), `--auto`(1순위), `--quant Q4_K_M`(양자화 지정), `--top 8`(표시 개수), `--repo 저장소`(llmfit 순위에 없는 모델을 직접 지정, `--quant` 필요), `--gguf 파일경로`(이미 있는 파일 사용, `--copy` 로 `models/` 에 복사).
`serve.py start` 옵션: `--slots 2`(동시 요청 수), `--ctx-per-slot 49152`(슬롯당 컨텍스트), `--port 8080`, `--wait 300`(대기 초).

### 2.4 점검 결과 읽는 법

| 결과 | 의미 | 할 일 |
|---|---|---|
| `PASS` | 도구 호출과 강도 예측이 정상 | 그대로 진행 |
| `WARN` | 강도 예측이 "가장 가까운 합금 평균"보다 나쁨 | 더 큰 모델 권장 |
| `FAIL` | 답이 올바른 JSON 이 아니거나 도구 호출 불가 (`--agent` 는 설계 전체 실패) | 더 큰 모델을 고르세요 (2.5) |

### 2.5 어떤 모델을 고를까

- 가벼운 모델(4B 급): 설치·점검은 통과하지만 설계 루프가 끝까지 돌지 않는 경우가 대부분입니다.
- **권장: Qwen3.8-27B** (`unsloth/Qwen3.8-27B-GGUF`, Q4_K_M 약 15GB). 이 저장소의 설계 루프를 만들고 검증할 때 쓴 모델이고, 품질 점검의 기준값(6xxx UTS 오차 약 23 MPa)도 이 모델입니다. 이 저장소의 서버 설정(`llm/serve.py`)으로 다시 돌려 확인한 것은 아니므로 먼저 `llm/selfcheck.py --agent` 로 점검하세요. 실패해도 같은 명령을 다시 실행하면 됩니다.
- 모델을 바꾸려면 `.venv\Scripts\python.exe llm/serve.py stop` → `.venv\Scripts\python.exe llm/pick.py --repo unsloth/Qwen3.8-27B-GGUF --quant Q4_K_M` (또는 `llm/pick.py --quant Q4_K_M` 로 순위에서 선택) → `.venv\Scripts\python.exe llm/serve.py start` 순서로 합니다.

## 3. 설계 실행

모델 서버가 켜져 있어야 합니다 (`.venv\Scripts\python.exe llm/serve.py status` 로 확인).

### 3.1 한 줄 실행

```powershell
.venv\Scripts\python.exe design.py "6xxx T6 압출, UTS 330 MPa 이상, 연신율 10% 이상, 내식성 좋게"
```

몇 분 걸립니다 (모델과 PC 에 따라 5~10분). 끝나면 후보표가 화면에 나오고 `results/날짜-시간.md` 에 저장됩니다.
설계가 끝나지 않았을 때(모델이 도구 호출 형식을 못 맞춘 경우)는 `경고: 설계가 끝나지 않았습니다` 가 출력되고 종료 코드가 2 입니다. 같은 명령을 다시 실행하거나 더 큰 모델을 쓰세요.

### 3.2 옵션

| 명령 | 설명 |
|---|---|
| `design.py "요구사항"` | 요구사항을 문장으로 입력 |
| `design.py -f 요구사항.txt` | 파일에서 요구사항 읽기 |
| `design.py -v "요구사항"` | 도구 호출 과정(어떤 스크립트를 부르는지)을 화면에 표시 |
| `design.py --chat` | 대화형 모드 (`/quit` 종료, `/clear` 초기화) |
| `design.py --max-steps 24 "..."` | 도구 호출 라운드 상한 (기본 24) |
| `design.py -h` | 도움말 |

### 3.3 요구사항 쓰는 법

넣을 수 있는 조건: 합금 계열(2xxx, 5xxx, 6xxx, 7xxx, Al-Li, 주조 Al-Si), 강도(UTS/YTS), 연신율 하한, 밀도 상한, 내식성, 템퍼(T6 등), 공정(압출 등).
**숫자를 주지 않은 조건은 모델이 가정으로 채우고 "가정" 항목에 적습니다.** 지어낸 숫자를 요구로 넣지 마세요.

```powershell
.venv\Scripts\python.exe design.py "7xxx T6 판재, UTS 550 MPa 이상, 밀도 2.85 이하"
.venv\Scripts\python.exe design.py "경량 고강도 6xxx 압출재, 비강도 최대화, 연신율 8% 이상"
```

### 3.4 결과 읽는 법

| 항목 | 의미 |
|---|---|
| 해석한 설계 목표 / 가정 | 모델이 요구를 어떻게 해석했고 무엇을 가정했는지 |
| 추천 후보 표 | 조성(wt%, Al 잔부), 열처리, **ICL UTS ± 흩어짐**, **ML UTS/EL (80% 범위)**, 밀도, 비강도, 부식 규칙 통과 여부, 확인 필요 표시, 출발 합금 |
| 부식 근거 | 가장 가까운 합금의 실측·공칭 값과 시험 조건, 출처 DOI (예측이 아님) |
| 주의 / 부족한 부분 | 예측의 한계, 요구를 못 채운 부분 |

`확인 필요`, `조건 위반` 표시는 그대로 믿지 말고 표의 숫자를 직접 보세요. 설명 문장과 최종 조성이 어긋나는 경우가 있었습니다.

### 3.5 모델 없이 쓸 수 있는 것

실측 합금 조회는 모델이 필요 없습니다.

```powershell
.venv\Scripts\python.exe src/skills/alloy-properties/scripts/examples.py `
  --spec '{"series":"6xxx","temper":"T6","route":"extrusion","objectives":[{"property":"UTS","direction":"maximize","target":330}],"constraints":{"EL_min":10},"corrosion":true}' `
  --k 8
```

`score.py`(채점)는 강도 예측에 모델 서버가 필요합니다.

## 4. 서버 관리

| 하고 싶은 일 | 명령 |
|---|---|
| 상태 확인 | `.venv\Scripts\python.exe llm/serve.py status` |
| 켜기 | `.venv\Scripts\python.exe llm/serve.py start` |
| 끄기 | `.venv\Scripts\python.exe llm/serve.py stop` |
| 로그 보기 | `Get-Content .llm\server.log -Wait` |
| 선택된 모델 확인 | `Get-Content .llm\selection.json` |

### 다른 서버(Ollama, LM Studio 등) 쓰기

Ollama, LM Studio 의 **모델 파일**을 이 프로젝트 서버로 쓰는 것은 `bootstrap.py` 가 자동으로 합니다 (2.2 "이미 있는 모델 쓰기"). 그 서버 자체에 붙이려면 OpenAI 호환 서버면 됩니다 (이때 컨텍스트 길이 49152 이상과 생각(thinking) 끄기는 그 서버에서 직접 설정해야 합니다). `.env` 를 직접 고치세요 (끝에 `/v1` 을 붙이지 않습니다).

```
LLM_BASE_URL=http://127.0.0.1:11434   # Ollama 예시
LLM_MODEL=모델이름
LLM_SLOTS=2
LLM_CTX_PER_SLOT=49152
LLM_TIMEOUT=7200                      # 답 하나를 기다리는 최대 초 (0 = 무제한, GPU 없는 PC 는 0 권장)
```

## 5. 문제 해결

| 증상 | 원인 | 해결 |
|---|---|---|
| `.env 가 없습니다` | 모델 서버를 아직 켜지 않음 | `.venv\Scripts\python.exe llm/serve.py start` |
| `모델 서버가 응답하지 않습니다` | 서버가 꺼졌거나 죽음 | `serve.py status` → `serve.py start`, 그래도 안 되면 `Get-Content .llm\server.log -Tail 50` |
| 출력이 `<tool_call> {...}` 텍스트로 끝남 (`design.py` 는 경고를 내고 종료 코드 2) | 모델이 도구 호출 형식을 못 맞춤 (작은 모델) | 더 큰 모델로 교체 (2.5), 같은 명령을 다시 실행 |
| `[stopped: same call repeated]` | 모델이 같은 잘못된 호출을 반복 | 위와 같음 |
| `reply cut off at the context limit` | 모델의 한 답변이 끝없이 길어져 잘림 | 같은 명령을 다시 실행, 계속되면 더 큰 모델 |
| `모델 서버 응답 시간 초과` (`httpx.ReadTimeout`) | GPU 없이 CPU 로만 돌면 대화가 길어질수록 답 하나에 30분 이상 걸림 (기본 제한 7200초) | `.env` 에 `LLM_TIMEOUT=0`(무제한)을 넣고 다시 실행. 노트북은 전원을 연결하고 Windows 전원 모드를 `최고 성능`으로. 근본 해결은 GPU |
| `give 1-8 candidates per call` 등 인자 오류가 반복 | 모델이 `score.py` 입력 형식을 못 지킴 | 모델이 스스로 고치기도 합니다. 계속되면 더 큰 모델 |
| 한 번 돌리는 데 너무 오래 걸림 | 모델이 크거나 PC 가 느림 | 더 작은 양자화(`--quant Q4_K_M`) 또는 작은 모델. 열이 많이 나면 중간에 `Ctrl+C` |
| `llmfit` 이 없다고 나옴 | 미설치 | `pick.py` 가 설치 여부를 물어봅니다. 직접: `scoop install llmfit` 또는 `uv tool install llmfit` |
| 8080 포트가 사용 중 | 다른 프로그램이 사용 | `.venv\Scripts\python.exe llm/serve.py start --port 8090` (그러면 `.env` 의 주소도 자동 갱신) |
| 다운로드가 멈춤 | 네트워크 | 같은 `pick.py` 명령을 다시 실행 (처음부터 받습니다) |
| (WSL) 재부팅했는데 계속 "다시 시작하면 변경 사항이 적용됩니다" | 시작 메뉴의 `다시 시작` 이 기능 적용을 미룸 | PowerShell 에서 `shutdown /r /t 0`. `install-wsl.ps1` 은 이렇게 재부팅합니다 |
| (WSL) `wsl` 명령이 아무 반응 없이 멈춤 | Ubuntu 첫 실행 화면(사용자 이름·동의 질문)이 입력을 기다리는 중 | 열린 Ubuntu 창에서 질문에 답하거나 창을 닫고 `wsl --shutdown`. `install-wsl.ps1` 은 첫 실행 화면을 끄고 계정을 직접 만듭니다 |
| (WSL) apt 가 `Release file ... is not valid yet` | 미러의 Release 파일 날짜가 미래로 찍힘 (PC 시계 문제가 아님) | `sudo apt-get -o Acquire::Max-FutureTime=86400 update`. `bootstrap.py`, `install-wsl.ps1` 은 이 옵션을 씁니다 |
| (WSL, NVIDIA) `CUDA 13.2 이상이 필요한데 ... 드라이버는 CUDA 13.x 까지만` | Windows 의 NVIDIA 드라이버가 오래됨. Ubuntu 26.04(glibc 2.43)는 CUDA 13.1 이하와 컴파일이 안 됨 | Windows 에서 NVIDIA 드라이버 업데이트 → `install.cmd` 다시 실행 (GPU 로 다시 빌드) |
| (WSL) `python: command not found` | Ubuntu 에는 `python` 명령이 없음 | `python3 bootstrap.py` 로 실행 (설치 후에는 `.venv/bin/python`) |
| (WSL) 모델이 메모리에 안 들어감, 서버가 죽음 | WSL 기본 메모리 상한이 RAM 의 50% | `%UserProfile%\.wslconfig` 에 `[wsl2]` / `memory=20GB` 후 `wsl --shutdown` |

## 6. 정리하기

```powershell
.venv\Scripts\python.exe llm/serve.py stop      # 서버 끄기
Remove-Item -Recurse -Force models      # 내려받은 모델 삭제 (수 GB ~ 수십 GB)
Remove-Item -Recurse -Force .venv, .llm, runs, results, .env   # 환경·로그·결과 삭제 (모두 다시 만들 수 있음)
uv cache prune                          # 쓰지 않는 uv 캐시 정리 (선택)
```

## 7. 구조, 데이터, 라이선스

```
install.cmd                Windows: 더블클릭하면 install-wsl.ps1 실행
install-wsl.ps1            Windows: WSL2 + Ubuntu 를 만들고 그 안에서 bootstrap.py 까지 실행
bootstrap.py               환경 감지 + 한 번에 설치 (setup.sh 는 macOS/Linux 용 간단판)
design.py                  설계 실행 (CLI)
llm/                       pick.py(모델 추천·다운로드), existing.py(이미 있는 모델 찾기), serve.py(서버), selfcheck.py(품질 점검)
src/mcp/host/              모델 ↔ 스킬 ↔ KG 도구를 잇는 에이전트 루프
src/mcp/servers/kg/        지식그래프 MCP 서버
src/skills/                alloy-properties(다물성 설계), alloy-strength(ICL 강도 엔진, ML 모델)
data/alloy-properties/     강도 표(v1, v2, 논문 행), JSM·Tamura 2020 데이터
ontology/al_alloy/         al6xxx, alml 지식그래프(스키마, 규칙, 질의, build/kg.ttl)
scripts/strip_quotes.py    KG 에서 논문 원문 인용을 제거하는 도구
scripts/install-cuda-wsl.sh  WSL 에 CUDA 빌드 도구만 설치 (드라이버 없음, bootstrap.py / install-wsl.ps1 이 자동으로 씀)
```

- 코드: MIT (`LICENSE`).
- `data/` 는 공개된 강도 데이터(Mendeley, Ji, Hu, Mo 등)를 합친 표와 JSM 부식 표, Tamura 2020 보충자료입니다. 출처별 재배포 조건은 확인하지 않았으니 이 저장소 밖에서 쓸 때는 각 출처의 조건을 확인하세요.
- 지식그래프에는 논문에서 추출한 값과 DOI·페이지가 있고, 논문 원문 인용은 제거했습니다.
- 모델 가중치는 Hugging Face 에서 각 모델의 라이선스에 따라 내려받습니다 (`pick.py` 목록에서 확인).
