# Windows 설치 안내 (명령어, 처음 쓰는 분용)

Windows PC 에서 **명령어(CLI)로** Al Alloy Design 을 설치하고 첫 설계를 돌리기까지의 전 과정입니다.
설치 스크립트가 PC(WSL 유무, GPU, 메모리)를 확인해서 필요한 것만 설치합니다.

---

## 0. 한눈에 보기

| 내 PC | 실행할 곳 | 명령 |
|---|---|---|
| WSL(Ubuntu) 이 **이미 있음** | Ubuntu 터미널 | `git clone` → `python3 bootstrap.py --yes` (2.1) |
| WSL 이 **없음** | Windows PowerShell | `install-wsl.ps1` 받아서 실행 (2.2) |

| 걸리는 시간 | 30분 ~ 1시간 30분 (대부분 모델 다운로드와 빌드) |
|---|---|
| 필요한 것 | Windows 10 (2004 이상) 또는 Windows 11, 인터넷, 디스크 여유 30GB 이상 |
| 직접 하는 일 | 명령 입력, (WSL 새로 설치 시) 관리자 권한 `예`·재부팅·리눅스 사용자 이름과 비밀번호, (NVIDIA 이면) sudo 비밀번호 |
| 자동으로 하는 일 | GPU/CPU 판단, CUDA 빌드 도구(NVIDIA), 프로그램 빌드, 파이썬 환경, 모델 고르기·다운로드, 모델 서버, 품질 점검 |

> WSL 이 있는지 모르겠으면 PowerShell 에서 `wsl -l -v` → `Ubuntu ... 2` 가 보이면 있음.

---

## 1. 설치 전에 확인할 것

### 1.1 내 PC 가 어떤 경우인지

설치 스크립트가 자동으로 판단합니다. 미리 알아 두면 걸리는 시간과 결과를 예상할 수 있습니다.

| 내 PC | 설치되는 방식 | 자동으로 고르는 모델 | 설계 한 번 걸리는 시간 |
|---|---|---|---|
| NVIDIA GPU, VRAM 24GB 이상 | GPU (CUDA) | Qwen3.8-27B (약 15GB) | 예상: 수 분 ~ 10여 분 (README: 5~10분) |
| NVIDIA GPU, VRAM 10~24GB | GPU (CUDA) | Qwen3-14B (약 9GB) | 예상: 수 분 ~ 20분 |
| NVIDIA 가 아님 (Intel/AMD 내장 그래픽 등), 메모리 32GB | CPU | Qwen3-14B (약 9GB) | **실측 약 3시간** (Core Ultra 7 노트북, 6xxx 예시 요구사항) |
| 그보다 작은 메모리/VRAM | CPU 또는 GPU | llmfit 이 고른 더 작은 모델 | 작은 모델은 설계가 끝까지 안 될 수 있음 |

내 GPU 확인 (PowerShell):

```powershell
Get-CimInstance Win32_VideoController | Select-Object Name
```

### 1.2 NVIDIA GPU 가 있다면: 드라이버

GPU 로 돌리려면 Windows 에 **최신 NVIDIA 드라이버**가 있어야 합니다.

```powershell
nvidia-smi
```

맨 위 줄의 `CUDA Version:` 이 **13.2 이상**이면 됩니다. 명령이 없거나 버전이 낮으면 <https://www.nvidia.com/Download/index.aspx> 에서 설치·업데이트하세요.
WSL 안에서도 같은 명령(`nvidia-smi`)이 표를 보여 주면 준비된 것입니다. **리눅스용 NVIDIA 드라이버는 설치하지 마세요** (WSL 은 Windows 드라이버를 그대로 씁니다).

### 1.3 노트북이라면

- 전원 어댑터를 연결하고, `설정` → `시스템` → `전원` → 전원 모드 **최고 성능**.
- 설치와 설계가 도는 동안 노트북을 덮거나 절전되지 않게 하세요.

---

## 2. 설치

### 2.1 WSL(Ubuntu) 이 이미 있을 때

시작 메뉴에서 **Ubuntu** 를 열거나 PowerShell 에서 `wsl ~` 를 입력해 리눅스 터미널로 들어간 뒤:

```bash
git clone -b windows-support https://github.com/Godorina/al-alloy-design.git ~/al-alloy-design
cd ~/al-alloy-design
python3 bootstrap.py --yes
```

- **`-b windows-support` 를 꼭 붙이세요.** 빼면 기본 브랜치(`main`)가 받아지는데, 거기에는 이 설치 기능이 없습니다.
- `git: command not found` 가 나오면 먼저: `sudo apt update && sudo apt install -y git`
- 감지 결과와 할 일이 먼저 출력되고 바로 진행됩니다 (`--yes`). `--yes` 를 빼면 목록을 보고 `Y` 를 눌러 진행합니다.
- 할 일 목록만 보고 싶으면: `python3 bootstrap.py --detect-only`

출력 예 (NVIDIA 가 아닌 노트북):

```
감지 결과
  환경      WSL2 의 Linux (x86_64)
  메모리    19.5GB (WSL 에 할당된 양)
  GPU       감지 안 됨
  모델 예산 약 11.7GB

할 일
  1. uv 설치
  2. llama.cpp 빌드 (CPU, 수 분 걸립니다)
  3. 파이썬 환경 만들기 (.venv)
  4. 의존 패키지 설치
  5. llmfit 설치 (모델 추천·다운로드용)
  6. 모델 선택·다운로드
  7. 모델 서버 켜기 (동시 요청 1)
  8. 품질 점검 (selfcheck)
```

NVIDIA GPU PC 에서는 `GPU NVIDIA ..., VRAM 24.0GB, 드라이버 CUDA 13.x` 로 감지되고, 할 일에 `CUDA 빌드 도구 설치` 와 `llama.cpp 빌드 (CUDA, 10~30분 걸립니다)` 가 들어갑니다. CUDA 도구를 설치할 때 **sudo 비밀번호**를 물어봅니다.

> WSL 메모리: WSL 은 기본으로 PC 메모리의 절반만 씁니다. 모델이 크면 `C:\Users\내이름\.wslconfig` 에 아래를 넣고 PowerShell 에서 `wsl --shutdown` 후 다시 들어오세요 (2.2 의 스크립트는 자동으로 해 줍니다).
>
> ```ini
> [wsl2]
> memory=20GB
> ```

### 2.2 WSL 이 없을 때 (Windows PowerShell)

PowerShell 을 **일반 권한**으로 열고:

```powershell
cd $HOME\Downloads
irm https://raw.githubusercontent.com/Godorina/al-alloy-design/windows-support/install-wsl.ps1 -OutFile install-wsl.ps1
powershell -ExecutionPolicy Bypass -File .\install-wsl.ps1
```

이 스크립트가 WSL·Ubuntu 설치, 리눅스 계정, `.wslconfig` 메모리 설정을 한 뒤 Ubuntu 안에서 2.1 과 같은 일을 합니다.

| 옵션 | 뜻 |
|---|---|
| `-User 이름` | 리눅스 사용자 이름 (안 주면 물어봄) |
| `-Yes` | 확인 질문 생략. **재부팅도 묻지 않고 진행**하고, NVIDIA 드라이버 문제는 CPU 로 계속 |
| `-MemoryGB 20` | WSL 이 쓸 메모리 상한 (기본: PC 메모리의 약 65%) |
| `-ModelRepo unsloth/Qwen3-14B-GGUF` | 모델을 직접 지정 (기본: GPU/메모리에 맞춰 자동) |
| `-SkipBootstrap` | WSL 준비와 저장소 받기까지만 |
| `-NoExisting` | Ollama, LM Studio 등으로 이미 받아 둔 모델을 쓰지 않고 새로 다운로드 |

진행 중에 보이는 것과 할 일:

| 단계 | 화면 | 할 일 |
|---|---|---|
| [1] 사전 점검 | `OK  GPU: NVIDIA ... -> GPU 로 설치` 또는 `-> CPU 로 설치` | 없음 (NVIDIA 드라이버 문제면 "CPU 로 계속할까요?" → 1.2) |
| [2] Windows 기능 | 관리자 권한 창 (1~2번) | **`예`** |
| | `지금 재부팅할까요?` (처음 설치하는 PC 만) | 열린 작업을 저장하고 `Y` → 10초 뒤 재부팅 |
| (재부팅 후) | 로그인하면 **PowerShell 창이 자동으로 다시 열려** 이어서 진행 | 기다리기 |
| [3] Ubuntu 설치 | `Ubuntu 를 설치했습니다` | 없음 |
| [4] 리눅스 사용자 | `리눅스 사용자 이름 [...]` | 영문 소문자로 입력 (예: `alloy`) |
| | `New password:` / `Retype new password:` | 비밀번호 두 번. **화면에 안 보이는 게 정상**. 꼭 기억하세요 |
| [5] WSL 메모리 | `.wslconfig 에 memory=20GB 를 썼습니다` | 없음 |
| [6] 설치 (WSL 안) | apt, git clone, (NVIDIA 면) CUDA 빌드 도구, `bootstrap.py` | 기다리기 (가장 오래 걸림) |
| [요약] | 계산 장치, 모델, 모델 서버 | 결과 확인 (2.3) |

Windows 에 Ollama 나 LM Studio 로 받아 둔 모델(7B 이상, 도구 호출 지원)이 있으면 [6] 단계에서 그 파일을 WSL 안으로 한 번 복사해 쓰고, 다운로드는 건너뜁니다 (README 2.2 "이미 있는 모델 쓰기"). 새로 받고 싶으면 `-NoExisting` 을 붙이세요.

중간에 멈추거나 창을 닫았으면 **같은 명령을 다시 실행**하세요. 끝난 단계는 건너뜁니다.

### 2.3 잘 끝났는지 확인

```
품질 점검 (selfcheck)
tool calling: ok
PASS: UTS MAE 19.9 MPa vs nearest-neighbour 30.6 MPa (1096s). ...

끝났습니다. 설계 실행: .../.venv/bin/python design.py "..."
```

- `품질 점검` 뒤 10~20분(CPU) 동안 아무 출력이 없어도 정상입니다 (모델이 12문제를 푸는 중).

| 점검 결과 | 의미 |
|---|---|
| `PASS` | 정상 |
| `WARN` | 동작은 하지만 강도 예측이 덜 정확함. 더 큰 모델 권장 |
| `FAIL` | 모델이 너무 작아 설계가 잘 안 됨. 설치는 끝났지만 더 큰 모델 필요 (README 2.5) |

GPU 를 실제로 쓰는지 확인 (Ubuntu 에서):

```bash
~/.local/bin/llama-server --list-devices
```

`CUDA0: NVIDIA ...` 가 보이면 GPU, `(none)` 이면 CPU 입니다.

---

## 3. 첫 설계 실행

설치가 끝나면 **Ubuntu 터미널을 닫고 새로 엽니다** (설치 중 생긴 `~/.local/bin` 을 새 터미널부터 인식합니다).

```bash
cd ~/al-alloy-design
.venv/bin/python design.py -v "6xxx T6 압출, UTS 330 MPa 이상, 연신율 10% 이상, 내식성 좋게"
```

- `-v` 를 붙이면 모델이 어떤 도구를 부르는지 보입니다 (`⚙ MCP 도구 사용: ...`). 멈춘 것인지 헷갈리지 않게 붙이는 것을 권장합니다.
- 끝나면 후보 합금 표가 화면에 나오고 `results/날짜-시간.md` 로 저장됩니다.
- **CPU PC 는 약 3시간** 걸릴 수 있습니다 (테스트 노트북 실측). 한 줄이 나온 뒤 수십 분 조용해도 계산 중입니다.

다른 요구사항 예:

```bash
.venv/bin/python design.py -v "7xxx T6 판재, UTS 550 MPa 이상, 밀도 2.85 이하"
.venv/bin/python design.py -v "경량 고강도 6xxx 압출재, 비강도 최대화, 연신율 8% 이상"
.venv/bin/python design.py -f 요구사항.txt      # 파일에서 읽기
.venv/bin/python design.py --chat              # 대화형 (/quit 종료)
```

넣을 수 있는 조건: 합금 계열(2xxx, 5xxx, 6xxx, 7xxx, Al-Li, 주조 Al-Si), 강도(UTS/YTS), 연신율 하한, 밀도 상한, 내식성, 템퍼(T6 등), 공정(압출 등). 숫자를 주지 않은 조건은 모델이 가정으로 채웁니다.

결과 보기:

```bash
ls ~/al-alloy-design/results
cat ~/al-alloy-design/results/<파일이름>.md
```

(Windows 탐색기에서는 `\\wsl.localhost\Ubuntu\home\<리눅스사용자>\al-alloy-design\results`)

---

## 4. 매일 쓸 때 (모델 서버 관리)

설계를 하려면 **모델 서버**가 켜져 있어야 합니다. 서버는 메모리(또는 VRAM)를 많이 차지하므로 안 쓸 때는 꺼 두세요.
PC 를 재부팅하거나 절전하면 서버가 꺼집니다. 그때는 `켜기` 부터 하세요.

```bash
cd ~/al-alloy-design
.venv/bin/python llm/serve.py status              # healthy: True 면 준비됨
.venv/bin/python llm/serve.py start --slots 1     # 켜기 (약 1분). VRAM 24GB 이상 GPU 는 --slots 2
.venv/bin/python llm/serve.py stop                # 끄기
```

---

## 5. CPU PC 에서 쓸 때 알아 둘 것

GPU 없이 CPU 로만 돌면 대화가 길어질수록 느려집니다 (테스트한 8스레드 노트북: 질문 하나에 1분 ~ 30분 이상).

- 기본 설정은 답 하나를 **최대 2시간** 기다립니다. 그보다 오래 걸리면 `모델 서버 응답 시간 초과` 가 나옵니다.
- 시간 제한을 없애려면:

  ```bash
  echo "LLM_TIMEOUT=0" >> ~/al-alloy-design/.env
  ```

- 전원 연결 + 전원 모드 `최고 성능` 이 체감상 가장 큰 차이를 만듭니다.

---

## 6. 업데이트

저장소가 바뀌었을 때:

```bash
cd ~/al-alloy-design
git pull
python3 bootstrap.py --yes      # 빠진 것만 설치. 모델·빌드는 그대로 두고, 품질 점검은 다시 함 (CPU 약 20분)
```

GPU 를 나중에 달았거나 드라이버를 업데이트했으면 `python3 bootstrap.py --yes` 만 다시 실행하면 CPU 빌드를 CUDA 로 다시 빌드합니다.

---

## 7. 문제 해결

| 증상 | 원인 | 해결 |
|---|---|---|
| `python: command not found` | Ubuntu 에는 `python` 명령이 없음 | `python3 bootstrap.py` 로 실행 (설치 후에는 `.venv/bin/python`) |
| apt 가 `Release file ... is not valid yet` | 미러의 날짜 문제 (PC 시계 문제 아님) | `sudo apt-get -o Acquire::Max-FutureTime=86400 update` (`bootstrap.py` 는 자동으로 씀) |
| `wsl` 명령이 아무 반응 없이 멈춤 | Ubuntu 첫 실행 화면이 입력을 기다리는 중 | 열린 Ubuntu 창의 질문에 답하거나 창을 닫고 `wsl --shutdown` |
| 재부팅 후에도 계속 "다시 시작하면 적용됩니다" | 시작 메뉴의 `다시 시작` 이 기능 적용을 미룸 | PowerShell 에서 `shutdown /r /t 0` |
| `가상화가 활성화되지 않은 이 컴퓨터에서는 WSL2를 시작할 수 없습니다` | BIOS 에서 가상화가 꺼짐 | BIOS/UEFI 에서 Intel VT-x / AMD SVM 켜기 |
| [1] 에서 `NVIDIA GPU 가 있지만 드라이버가 ...` | 드라이버 없음/오래됨 | 드라이버 설치·업데이트 후 같은 명령 다시 실행 (GPU 로 다시 빌드) |
| `CUDA 13.2 이상이 필요한데 ... 드라이버는 CUDA 13.x 까지만` | Windows NVIDIA 드라이버가 오래됨 | 드라이버 업데이트 → `python3 bootstrap.py --yes` |
| NVIDIA PC 인데 `--list-devices` 가 `(none)` | CUDA 빌드 도구 설치 또는 빌드 실패 | 출력에서 `CUDA` 부분 확인, Ubuntu 에서 `nvidia-smi` 가 되는지 확인 |
| Ubuntu 에서 `nvidia-smi` 가 안 됨 | WSL 이 오래됨 | PowerShell 에서 `wsl --update` → `wsl --shutdown` |
| `llama-server not found` | 설치 직후 터미널은 경로가 갱신 안 됨 | 터미널을 닫고 새로 열기 |
| `모델 서버가 응답하지 않습니다` | 서버가 꺼짐 (재부팅·절전 후) | 4장의 `start` |
| `모델 서버 응답 시간 초과` | CPU 로 너무 오래 걸림 | 5장 `LLM_TIMEOUT=0` |
| `설계가 끝나지 않았습니다 (모델이 도구 호출 형식을 맞추지 못함)` | 모델이 작음 | 같은 명령 다시 실행, 계속되면 더 큰 모델 (README 2.5) |
| 그 밖의 오류 | | 오류 메시지와 로그를 함께 알려 주세요 |

로그: 설치 스크립트 `%LOCALAPPDATA%\al-alloy-design\install-wsl.log`, 모델 서버 `tail -50 ~/al-alloy-design/.llm/server.log`

---

## 8. 무엇이 어디에 설치되나

| 위치 | 내용 | 크기 |
|---|---|---|
| `~/al-alloy-design` | 프로그램, 파이썬 환경(`.venv`), 모델(`models/`), 결과(`results/`), 설정(`.env`) | 모델 9~15GB + 1GB |
| `~/llama.cpp` | 모델 서버 프로그램 (소스에서 빌드) | 약 0.3GB |
| `~/.local` | uv, llmfit, 파이썬 3.12, `llama-server` 링크 | 수백 MB |
| `/usr/local/cuda` | (NVIDIA PC 만) CUDA 빌드 도구 (nvcc, cuBLAS) | 다운로드 약 1GB |
| `C:\Users\내이름\.wslconfig` | (2.2 사용 시) WSL 메모리 상한 | 작음 |

다른 PC 로 옮길 때는 폴더를 복사하지 말고 그 PC 에서 2장을 새로 실행하세요. 빌드와 파이썬 환경은 PC(CPU·GPU·경로)에 묶여 있어 복사하면 동작하지 않습니다.

---

## 9. 지우기

이 프로그램만 (Ubuntu 에서):

```bash
~/al-alloy-design/.venv/bin/python ~/al-alloy-design/llm/serve.py stop
rm -rf ~/al-alloy-design ~/llama.cpp
```

WSL(Ubuntu) 까지 모두 — 관리자 PowerShell 에서 (**Ubuntu 안의 모든 파일이 지워집니다**):

```powershell
wsl --unregister Ubuntu
wsl --uninstall
Remove-Item "$env:USERPROFILE\.wslconfig", "$env:LOCALAPPDATA\al-alloy-design" -Recurse -ErrorAction SilentlyContinue
```
