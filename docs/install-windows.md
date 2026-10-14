# Windows 설치 안내 (처음 쓰는 분용)

Windows PC 에 **파일 하나(`install.cmd`)만 실행**해서 Al Alloy Design 을 설치하고 첫 설계를 돌리기까지의 전 과정입니다.
리눅스, 파이썬, git 을 몰라도 됩니다. 설치 스크립트가 PC 를 확인해서 필요한 것만 설치합니다.

---

## 0. 한눈에 보기

```
GitHub 에서 ZIP 받기 → install.cmd 더블클릭 → (관리자 권한 '예', 필요하면 재부팅, 리눅스 비밀번호) → 기다리기 → 끝
```

| 걸리는 시간 | 30분 ~ 1시간 30분 (대부분 모델 다운로드와 빌드) |
|---|---|
| 필요한 것 | Windows 10 (2004 이상) 또는 Windows 11, 인터넷, 디스크 여유 30GB 이상 |
| 직접 하는 일 | 관리자 권한 창에서 `예`, (필요하면) 재부팅 확인, 리눅스 사용자 이름·비밀번호 입력 |
| 자동으로 하는 일 | WSL(Windows 안의 리눅스) 설치, Ubuntu 설치, 메모리 설정, GPU 확인, 프로그램 빌드, 모델 다운로드, 품질 점검 |

---

## 1. 설치 전에 확인할 것

### 1.1 내 PC 가 어떤 경우인지

설치 스크립트가 자동으로 판단하지만, 미리 알아 두면 걸리는 시간과 결과를 예상할 수 있습니다.

| 내 PC | 설치되는 방식 | 자동으로 고르는 모델 | 설계 한 번 걸리는 시간 |
|---|---|---|---|
| NVIDIA GPU, VRAM 24GB 이상 | GPU (CUDA) | Qwen3.8-27B (약 15GB) | 예상: 수 분 ~ 10여 분 (README: 5~10분) |
| NVIDIA GPU, VRAM 10~24GB | GPU (CUDA) | Qwen3-14B (약 9GB) | 예상: 수 분 ~ 20분 |
| NVIDIA 가 아님 (Intel/AMD 내장 그래픽 등), 메모리 32GB | CPU | Qwen3-14B (약 9GB) | **실측 약 3시간** (Core Ultra 7 노트북, 6xxx 예시 요구사항) |
| 그보다 작은 메모리/VRAM | CPU 또는 GPU | llmfit 이 고른 더 작은 모델 | 작은 모델은 설계가 끝까지 안 될 수 있음 |

> 내 GPU 확인: 작업 관리자(`Ctrl+Shift+Esc`) → `성능` 탭 → `GPU` 항목의 이름.

### 1.2 NVIDIA GPU 가 있다면: 드라이버

GPU 로 돌리려면 Windows 에 **최신 NVIDIA 드라이버**가 있어야 합니다. PowerShell 에서 확인합니다.

```powershell
nvidia-smi
```

맨 위 줄의 `CUDA Version:` 이 **13.2 이상**이면 됩니다. 명령이 없다고 나오거나 버전이 낮으면 <https://www.nvidia.com/Download/index.aspx> 에서 드라이버를 설치·업데이트하세요.
(확인하지 않고 바로 설치해도 됩니다. 스크립트가 1단계에서 확인하고, 문제가 있으면 "CPU 로 계속할지 / 드라이버 페이지를 열고 멈출지" 물어봅니다.)

> 리눅스용 NVIDIA 드라이버는 설치하지 마세요. WSL 은 Windows 드라이버를 그대로 씁니다.

### 1.3 노트북이라면

- 전원 어댑터를 연결하세요.
- `설정` → `시스템` → `전원` → 전원 모드를 **최고 성능**으로 바꾸세요. (배터리·절전 모드에서는 훨씬 느립니다)
- 설치와 설계가 도는 동안 노트북을 덮거나 절전되지 않게 하세요.

---

## 2. 설치

### 2.1 받기

1. <https://github.com/Godorina/al-alloy-design/tree/windows-support> 에 들어갑니다.
2. 초록색 **`Code`** 버튼 → **`Download ZIP`** 을 누릅니다.
3. 받은 ZIP 을 **다운로드 폴더에 바로** 압축 해제합니다.
   - 폴더를 여러 단계 깊이 만들어 풀면 Windows 경로 길이 제한(260자)에 걸릴 수 있습니다.

### 2.2 실행

압축을 푼 폴더(`al-alloy-design-windows-support`)의 **`install.cmd` 를 더블클릭**합니다.

- "Windows의 PC 보호" 파란 창이 뜨면 → `추가 정보` → `실행`.
- 검은 창이 열리고 진행 상황이 나옵니다. **끝날 때까지 창을 닫지 마세요.**

### 2.3 진행 중에 보이는 것과 할 일

| 단계 | 화면 | 할 일 |
|---|---|---|
| [1] 사전 점검 | `OK  GPU: NVIDIA ... -> GPU 로 설치` 또는 `-> CPU 로 설치` | 없음 (NVIDIA 드라이버 문제면 질문이 나옴 → 1.2 참고) |
| [2] Windows 기능 | 관리자 권한 창 (1~2번) | **`예`** |
| | `지금 재부팅할까요?` (처음 설치하는 PC 만) | 열린 작업을 저장하고 `Y` → 10초 뒤 재부팅 |
| (재부팅 후) | 로그인하면 **설치 창이 자동으로 다시 열림** | 기다리기 |
| [3] Ubuntu 설치 | `Ubuntu 를 설치했습니다` | 없음 |
| [4] 리눅스 사용자 | `리눅스 사용자 이름 [...]` | 영문 소문자로 입력 (예: `alloy`). Enter 만 누르면 괄호 안 이름 |
| | `New password:` / `Retype new password:` | 비밀번호 두 번 입력. **화면에 안 보이는 게 정상**. 꼭 기억하세요 |
| [5] WSL 메모리 | `.wslconfig 에 memory=20GB 를 썼습니다` | 없음 |
| [6] 설치 (WSL 안) | apt, git clone, (NVIDIA 면) CUDA 빌드 도구, llama.cpp 빌드, 모델 다운로드 | 기다리기 (가장 오래 걸림) |
| | `품질 점검 (selfcheck)` 뒤 몇 분~십여 분 아무 출력이 없음 | **정상**. 모델이 12문제를 푸는 중 |
| [요약] | 계산 장치, 모델, 모델 서버 | 결과 확인 (2.4) |

### 2.4 잘 끝났는지 확인

마지막에 이런 내용이 나오면 성공입니다.

```
PASS: UTS MAE 19.9 MPa vs nearest-neighbour 30.6 MPa (...)

[요약] 설치 결과
    OK  계산 장치: GPU (CUDA0: NVIDIA GeForce RTX ...)     ← GPU PC
    OK  계산 장치: CPU                                       ← NVIDIA 가 아닌 PC
    OK  모델: unsloth/Qwen3-14B-GGUF (Q4_K_M)
    OK  모델 서버: 켜져 있음 (http://127.0.0.1:8080)

끝났습니다.
```

| 점검 결과 | 의미 |
|---|---|
| `PASS` | 정상 |
| `WARN` | 동작은 하지만 강도 예측이 덜 정확함. 더 큰 모델 권장 |
| `FAIL` | 모델이 너무 작아 설계가 잘 안 됨. 설치는 끝났지만 더 큰 모델 필요 (README 2.5) |

> NVIDIA PC 인데 요약에 `계산 장치: CPU (GPU 로 빌드되지 않았습니다 ...)` 가 나오면 7장 문제 해결을 보세요.

---

## 3. 첫 설계 실행

### 3.1 Ubuntu 열기

시작 메뉴에서 **Ubuntu** 를 검색해서 엽니다. (또는 PowerShell 에서 `wsl ~`)

```
alloy@내PC이름:~$
```

이런 프롬프트가 나오면 리눅스 안입니다.

### 3.2 실행

```bash
cd ~/al-alloy-design
.venv/bin/python design.py -v "6xxx T6 압출, UTS 330 MPa 이상, 연신율 10% 이상, 내식성 좋게"
```

- `-v` 를 붙이면 모델이 어떤 도구를 부르는지 보입니다 (`⚙ MCP 도구 사용: ...`). 멈춘 것인지 헷갈리지 않게 붙이는 것을 권장합니다.
- 끝나면 후보 합금 표가 화면에 나오고 `results/날짜-시간.md` 로 저장됩니다.
- **CPU PC 는 약 3시간** 걸릴 수 있습니다 (테스트 노트북 실측). 한 줄이 나온 뒤 수십 분 조용해도 계산 중입니다.

### 3.3 요구사항 바꿔 보기

따옴표 안의 문장만 바꿉니다.

```bash
.venv/bin/python design.py -v "7xxx T6 판재, UTS 550 MPa 이상, 밀도 2.85 이하"
.venv/bin/python design.py -v "경량 고강도 6xxx 압출재, 비강도 최대화, 연신율 8% 이상"
```

넣을 수 있는 조건: 합금 계열(2xxx, 5xxx, 6xxx, 7xxx, Al-Li, 주조 Al-Si), 강도(UTS/YTS), 연신율 하한, 밀도 상한, 내식성, 템퍼(T6 등), 공정(압출 등). 숫자를 주지 않은 조건은 모델이 가정으로 채웁니다.

### 3.4 결과 파일 보기

Windows 탐색기 주소창에 붙여 넣으면 결과 폴더가 열립니다 (`alloy` 는 내 리눅스 사용자 이름으로).

```
\\wsl.localhost\Ubuntu\home\alloy\al-alloy-design\results
```

---

## 4. 매일 쓸 때 (모델 서버 관리)

설계를 하려면 **모델 서버**가 켜져 있어야 합니다. 서버는 메모리(또는 VRAM)를 많이 차지하므로 안 쓸 때는 꺼 두세요.
PC 를 재부팅하거나 절전하면 서버가 꺼집니다. 그때는 `켜기` 부터 하세요.

모든 명령은 Ubuntu 에서 `cd ~/al-alloy-design` 한 뒤에 실행합니다.

| 하고 싶은 일 | 명령 |
|---|---|
| 서버 상태 확인 | `.venv/bin/python llm/serve.py status` → `healthy: True` 면 준비됨 |
| 서버 켜기 (약 1분) | `.venv/bin/python llm/serve.py start --slots 1` (VRAM 24GB 이상 GPU 는 `--slots 2`) |
| 서버 끄기 | `.venv/bin/python llm/serve.py stop` |
| 설계 실행 | `.venv/bin/python design.py -v "요구사항"` |
| 대화형으로 쓰기 | `.venv/bin/python design.py --chat` (`/quit` 종료) |

---

## 5. CPU PC 에서 쓸 때 알아 둘 것

GPU 없이 CPU 로만 돌면 대화가 길어질수록 느려집니다 (테스트한 8스레드 노트북: 질문 하나에 1분 ~ 30분 이상).

- 기본 설정은 답 하나를 **최대 2시간** 기다립니다. 그보다 오래 걸리면 `모델 서버 응답 시간 초과` 가 나옵니다.
- 시간 제한을 없애려면 `~/al-alloy-design/.env` 에 한 줄을 추가합니다.

  ```bash
  echo "LLM_TIMEOUT=0" >> ~/al-alloy-design/.env
  ```

- 전원 연결 + 전원 모드 `최고 성능` 이 체감상 가장 큰 차이를 만듭니다.

---

## 6. 명령어로 설치하기 (선택)

ZIP 대신 PowerShell 에서 설치할 수도 있습니다. git 이 없어도 됩니다.

```powershell
cd $HOME\Downloads
irm https://raw.githubusercontent.com/Godorina/al-alloy-design/windows-support/install-wsl.ps1 -OutFile install-wsl.ps1
powershell -ExecutionPolicy Bypass -File .\install-wsl.ps1
```

| 옵션 | 뜻 |
|---|---|
| `-User 이름` | 리눅스 사용자 이름 (안 주면 물어봄) |
| `-Yes` | 확인 질문 생략. **재부팅도 묻지 않고 진행**하고, NVIDIA 드라이버 문제는 CPU 로 계속 |
| `-MemoryGB 20` | WSL 이 쓸 메모리 상한 (기본: PC 메모리의 약 65%) |
| `-ModelRepo unsloth/Qwen3-14B-GGUF` | 모델을 직접 지정 (기본: GPU/메모리에 맞춰 자동) |
| `-SkipBootstrap` | WSL 준비와 저장소 받기까지만 |

이미 WSL(Ubuntu) 이 있다면 Ubuntu 안에서 직접 설치해도 됩니다.

```bash
git clone -b windows-support https://github.com/Godorina/al-alloy-design.git ~/al-alloy-design
cd ~/al-alloy-design
python3 bootstrap.py --yes
```

---

## 7. 문제 해결

| 증상 | 원인 | 해결 |
|---|---|---|
| `install-wsl.ps1` 을 찾을 수 없다는 오류 | 압축을 풀지 않고 ZIP 안에서 `install.cmd` 를 실행 | ZIP 을 먼저 압축 해제한 뒤, 푼 폴더에서 실행 |
| 관리자 권한 창에서 `아니요` 를 누름 | 권한 없이 진행 불가 | `install.cmd` 다시 실행 → `예` |
| 재부팅했는데 설치 창이 다시 안 열림 | 자동 실행이 막힘 | `install.cmd` 를 다시 더블클릭 (끝난 단계는 건너뜀) |
| 재부팅 후에도 계속 "다시 시작하면 적용됩니다" | 시작 메뉴의 `다시 시작` 이 기능 적용을 미룸 | PowerShell 에서 `shutdown /r /t 0` 으로 재부팅 |
| `가상화가 활성화되지 않은 이 컴퓨터에서는 WSL2를 시작할 수 없습니다` | BIOS 에서 가상화가 꺼짐 | BIOS/UEFI 에서 Intel VT-x / AMD SVM(가상화) 켜기 |
| [1] 에서 `NVIDIA GPU 가 있지만 드라이버가 ...` | 드라이버 없음/오래됨 | `n` → 열린 페이지에서 드라이버 설치 → `install.cmd` 다시 실행 (GPU 로 다시 빌드) |
| NVIDIA PC 인데 요약이 `계산 장치: CPU` | CUDA 빌드 도구 설치 또는 빌드 실패 | 로그(아래)에서 `CUDA` 부분 확인. 드라이버 업데이트 후 `install.cmd` 다시 실행 |
| `Windows 에는 NVIDIA GPU 가 있지만 WSL 안에서 보이지 않습니다` | WSL 이 오래됨 | PowerShell 에서 `wsl --update` → 재부팅 → `install.cmd` 다시 실행 |
| Ubuntu 에서 `llama-server not found` | 설치 직후 연 창은 경로가 갱신 안 됨 | Ubuntu 창을 닫고 새로 열기 |
| `모델 서버가 응답하지 않습니다` | 서버가 꺼짐 (재부팅·절전 후) | 4장의 `서버 켜기` |
| `모델 서버 응답 시간 초과` | CPU 로 너무 오래 걸림 | 5장 `LLM_TIMEOUT=0` |
| `설계가 끝나지 않았습니다 (모델이 도구 호출 형식을 맞추지 못함)` | 모델이 작음 | 같은 명령 다시 실행, 계속되면 더 큰 모델 (README 2.5) |
| 그 밖의 오류 | | 빨간 `실패:` 메시지와 로그 파일을 함께 알려 주세요 |

**설치 로그**: 탐색기 주소창에 `%LOCALAPPDATA%\al-alloy-design` → `install-wsl.log`
**모델 서버 로그**: Ubuntu 에서 `tail -50 ~/al-alloy-design/.llm/server.log`

중간에 멈추거나 창을 닫았으면 **`install.cmd` 를 다시 실행**하면 됩니다. 끝난 단계는 건너뛰고 이어서 진행합니다.

---

## 8. 무엇이 어디에 설치되나

| 위치 | 내용 | 크기 |
|---|---|---|
| WSL 안 `~/al-alloy-design` | 프로그램, 파이썬 환경(`.venv`), 모델(`models/`), 결과(`results/`), 설정(`.env`) | 모델 9~15GB + 1GB |
| WSL 안 `~/llama.cpp` | 모델 서버 프로그램 (소스에서 빌드) | 약 0.3GB |
| WSL 안 `/usr/local/cuda` | (NVIDIA PC 만) CUDA 빌드 도구 (nvcc, cuBLAS) | 다운로드 약 1GB |
| `C:\Users\내이름\.wslconfig` | WSL 메모리 상한 설정 | 작음 |
| `%LOCALAPPDATA%\al-alloy-design` | 설치 로그 | 작음 |

다른 PC 로 옮길 때는 폴더를 복사하지 말고 그 PC 에서 `install.cmd` 를 새로 실행하세요. 빌드와 파이썬 환경은 PC(CPU·GPU·경로)에 묶여 있어 복사하면 동작하지 않습니다.

---

## 9. 지우기

Ubuntu 에서 이 프로그램만 지우기:

```bash
~/al-alloy-design/.venv/bin/python ~/al-alloy-design/llm/serve.py stop
rm -rf ~/al-alloy-design ~/llama.cpp
```

WSL(Ubuntu) 까지 모두 지우기 — 관리자 PowerShell 에서 (**Ubuntu 안의 모든 파일이 지워집니다**):

```powershell
wsl --unregister Ubuntu
wsl --uninstall
Remove-Item "$env:USERPROFILE\.wslconfig", "$env:LOCALAPPDATA\al-alloy-design" -Recurse -ErrorAction SilentlyContinue
```
