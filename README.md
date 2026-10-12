# Al Alloy Design — 알루미늄 합금 역설계 (CLI)

로컬 LLM과 실측 데이터로 "원하는 물성의 알루미늄 합금 조성"을 찾아 주는 도구입니다.
터미널 명령 하나로 실행합니다. (웹 화면이 필요하면 [docs/webui.md](docs/webui.md) — 선택 사항)

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
| 지원 환경 | macOS, Linux. Windows 는 지원하지 않습니다 (WSL2 는 확인하지 않았습니다) |
| 결과의 성격 | 강도(UTS/YTS)·연신율은 **예측값**입니다. 부식은 예측하지 않고 **가장 가까운 합금의 실측·공칭 값**을 보여 줍니다 |
| 모델 크기 | 모델이 작으면 설계 루프가 끝까지 돌지 않을 수 있습니다 (아래 2.5, 5장) |

## 1. 준비물

### 1.1 도구 설치

| 도구 | 용도 | 설치 명령 |
|---|---|---|
| git | 저장소 내려받기 | macOS: `xcode-select --install` / Linux: `sudo apt install git` |
| uv | 파이썬 환경 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` (설치 후 새 터미널) |
| llama.cpp | 모델 서버(`llama-server`) | macOS: `brew install llama.cpp` / Linux: <https://github.com/ggml-org/llama.cpp> 의 안내 |
| llmfit | 내 PC 에 맞는 모델 추천 | 따로 설치하지 않아도 됩니다. 2.2 단계에서 없으면 설치할지 물어봅니다 (macOS: `brew install AlexsJones/llmfit/llmfit`, 그 외: `uv tool install llmfit`) |

설치 확인:

```bash
git --version && uv --version && llama-server --version
```

### 1.2 여유 공간과 메모리

- 디스크: 모델 2~20GB(고른 모델에 따라) + 파이썬 환경 약 600MB
- 메모리: llmfit 이 내 PC 의 메모리에 들어가는 모델만 추천합니다. 시험한 PC 는 메모리 48GB 의 Apple Silicon Mac 이고, 다른 사양에서는 확인하지 않았습니다

## 2. 설치 (처음 한 번)

### 2.1 저장소 내려받기

```bash
gh repo clone Godorina/al-alloy-design      # 비공개 저장소: gh 로그인 필요 (gh auth login)
cd al-alloy-design
```

`gh` 가 없으면: `git clone https://github.com/Godorina/al-alloy-design.git` (계정 인증 필요)

### 2.2 한 번에 설치

권장 모델 Qwen3.8-27B(약 15GB)로 설치:

```bash
./setup.sh --repo unsloth/Qwen3.8-27B-GGUF --quant Q4_K_M
```

- `--repo` 는 Hugging Face 의 GGUF 저장소를 직접 지정하는 옵션입니다 (이 모델은 llmfit 순위 목록에 나오지 않습니다).
- `--quant Q4_K_M` 은 모델을 4비트 양자화로 받는 옵션입니다. 이 저장소에서는 `Qwen3.8-27B-UD-Q4_K_M.gguf` 한 파일이 선택됩니다.

가벼운 모델로 먼저 시험해 보려면 (설계 루프는 끝까지 돌지 않는 경우가 많습니다, 2.5 참고):

```bash
./setup.sh --quant Q4_K_M       # llmfit 순위에서 번호 선택 (예: Qwen3-4B)
```

실행되는 일은 4단계입니다. `--repo` 없이 실행하면 중간에 "Download which one? [1]" 이 나오고, 순위표의 번호를 입력합니다.

| 순서 | 하는 일 | 걸리는 시간 |
|---|---|---|
| 1 | `.venv` 만들고 `requirements.txt` 설치 | 1~2분 |
| 2 | llmfit 이 내 PC 사양으로 모델 순위를 보여 주고, 고른 모델을 `models/` 에 다운로드 | 모델 크기에 따라 |
| 3 | `llama-server` 를 켜고 `.env` 에 접속 정보를 기록 | 약 10초~1분 |
| 4 | 품질 점검(`selfcheck`): 도구 호출, 강도 예측 오차 | 1~2분 |

끝나면 `PASS` 또는 `WARN`/`FAIL` 한 줄이 나옵니다 (의미는 2.4).

### 2.3 단계별로 직접 하기 (setup.sh 를 쓰지 않을 때)

```bash
# (1) 파이썬 환경
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt

# (2) 모델 고르기 + 다운로드
.venv/bin/python llm/pick.py --list-only            # 순위만 보기
.venv/bin/python llm/pick.py --quant Q4_K_M         # 번호를 골라 다운로드
.venv/bin/python llm/pick.py --auto --quant Q4_K_M  # 묻지 않고 1순위 다운로드 (1순위는 큰 모델일 수 있으니 순위부터 확인)
.venv/bin/python llm/pick.py --repo unsloth/Qwen3.8-27B-GGUF --quant Q4_K_M   # 권장: Qwen3.8-27B 직접 지정 (약 15GB)

# (3) 모델 서버 켜기 (.env 가 자동으로 만들어짐)
.venv/bin/python llm/serve.py start

# (4) 품질 점검
.venv/bin/python llm/selfcheck.py                   # 도구 호출 + 강도 예측 (1~2분)
.venv/bin/python llm/selfcheck.py --agent           # 설계 전체 한 번 실행 (5~10분)
```

`pick.py` 옵션: `--list-only`(순위만), `--auto`(1순위), `--quant Q4_K_M`(양자화 지정), `--top 8`(표시 개수), `--repo 저장소`(llmfit 순위에 없는 모델을 직접 지정, `--quant` 필요).
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
- 모델을 바꾸려면 `.venv/bin/python llm/serve.py stop` → `.venv/bin/python llm/pick.py --repo unsloth/Qwen3.8-27B-GGUF --quant Q4_K_M` (또는 `llm/pick.py --quant Q4_K_M` 로 순위에서 선택) → `.venv/bin/python llm/serve.py start` 순서로 합니다.

## 3. 설계 실행

모델 서버가 켜져 있어야 합니다 (`.venv/bin/python llm/serve.py status` 로 확인).

### 3.1 한 줄 실행

```bash
.venv/bin/python design.py "6xxx T6 압출, UTS 330 MPa 이상, 연신율 10% 이상, 내식성 좋게"
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

```bash
.venv/bin/python design.py "7xxx T6 판재, UTS 550 MPa 이상, 밀도 2.85 이하"
.venv/bin/python design.py "경량 고강도 6xxx 압출재, 비강도 최대화, 연신율 8% 이상"
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

```bash
.venv/bin/python src/skills/alloy-properties/scripts/examples.py \
  --spec '{"series":"6xxx","temper":"T6","route":"extrusion","objectives":[{"property":"UTS","direction":"maximize","target":330}],"constraints":{"EL_min":10},"corrosion":true}' \
  --k 8
```

`score.py`(채점)는 강도 예측에 모델 서버가 필요합니다.

## 4. 서버 관리

| 하고 싶은 일 | 명령 |
|---|---|
| 상태 확인 | `.venv/bin/python llm/serve.py status` |
| 켜기 | `.venv/bin/python llm/serve.py start` |
| 끄기 | `.venv/bin/python llm/serve.py stop` |
| 로그 보기 | `tail -f .llm/server.log` |
| 선택된 모델 확인 | `cat .llm/selection.json` |

### 다른 서버(Ollama, LM Studio 등) 쓰기

OpenAI 호환 서버면 됩니다. `.env` 를 직접 고치세요 (끝에 `/v1` 을 붙이지 않습니다).

```
LLM_BASE_URL=http://127.0.0.1:11434   # Ollama 예시
LLM_MODEL=모델이름
LLM_SLOTS=2
LLM_CTX_PER_SLOT=49152
```

## 5. 문제 해결

| 증상 | 원인 | 해결 |
|---|---|---|
| `.env 가 없습니다` | 모델 서버를 아직 켜지 않음 | `.venv/bin/python llm/serve.py start` |
| `모델 서버가 응답하지 않습니다` | 서버가 꺼졌거나 죽음 | `serve.py status` → `serve.py start`, 그래도 안 되면 `tail .llm/server.log` |
| 출력이 `<tool_call> {...}` 텍스트로 끝남 (`design.py` 는 경고를 내고 종료 코드 2) | 모델이 도구 호출 형식을 못 맞춤 (작은 모델) | 더 큰 모델로 교체 (2.5), 같은 명령을 다시 실행 |
| `[stopped: same call repeated]` | 모델이 같은 잘못된 호출을 반복 | 위와 같음 |
| `reply cut off at the context limit` | 모델의 한 답변이 끝없이 길어져 잘림 | 같은 명령을 다시 실행, 계속되면 더 큰 모델 |
| `give 1-8 candidates per call` 등 인자 오류가 반복 | 모델이 `score.py` 입력 형식을 못 지킴 | 모델이 스스로 고치기도 합니다. 계속되면 더 큰 모델 |
| 한 번 돌리는 데 너무 오래 걸림 | 모델이 크거나 PC 가 느림 | 더 작은 양자화(`--quant Q4_K_M`) 또는 작은 모델. 열이 많이 나면 중간에 `Ctrl+C` |
| `llmfit` 이 없다고 나옴 | 미설치 | `pick.py` 가 설치 여부를 물어봅니다. 직접: `brew install AlexsJones/llmfit/llmfit` 또는 `uv tool install llmfit` |
| 8080 포트가 사용 중 | 다른 프로그램이 사용 | `.venv/bin/python llm/serve.py start --port 8090` (그러면 `.env` 의 주소도 자동 갱신) |
| 다운로드가 멈춤 | 네트워크 | 같은 `pick.py` 명령을 다시 실행 (처음부터 받습니다) |

## 6. 정리하기

```bash
.venv/bin/python llm/serve.py stop      # 서버 끄기
rm -rf models                           # 내려받은 모델 삭제 (수 GB ~ 수십 GB)
rm -rf .venv .llm runs results .env     # 환경·로그·결과 삭제 (모두 다시 만들 수 있음)
uv cache prune                          # 쓰지 않는 uv 캐시 정리 (선택)
```

## 7. 구조, 데이터, 라이선스

```
setup.sh                   한 번에 설치
design.py                  설계 실행 (CLI)
llm/                       pick.py(모델 추천·다운로드), serve.py(서버), selfcheck.py(품질 점검)
src/mcp/host/              모델 ↔ 스킬 ↔ KG 도구를 잇는 에이전트 루프
src/mcp/servers/kg/        지식그래프 MCP 서버
src/skills/                alloy-properties(다물성 설계), alloy-strength(ICL 강도 엔진, ML 모델)
data/alloy-properties/     강도 표(v1, v2, 논문 행), JSM·Tamura 2020 데이터
ontology/al_alloy/         al6xxx, alml 지식그래프(스키마, 규칙, 질의, build/kg.ttl)
openwebui/, webui.sh       Open WebUI 연동 (선택, docs/webui.md)
scripts/strip_quotes.py    KG 에서 논문 원문 인용을 제거하는 도구
```

- 코드: MIT (`LICENSE`).
- `data/` 는 공개된 강도 데이터(Mendeley, Ji, Hu, Mo 등)를 합친 표와 JSM 부식 표, Tamura 2020 보충자료입니다. 출처별 재배포 조건은 확인하지 않았으니 이 저장소 밖에서 쓸 때는 각 출처의 조건을 확인하세요.
- 지식그래프에는 논문에서 추출한 값과 DOI·페이지가 있고, 논문 원문 인용은 제거했습니다.
- 모델 가중치는 Hugging Face 에서 각 모델의 라이선스에 따라 내려받습니다 (`pick.py` 목록에서 확인).
