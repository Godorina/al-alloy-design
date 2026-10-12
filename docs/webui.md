# Open WebUI 로 쓰기 (선택)

기본 사용법은 CLI 입니다 ([README](../README.md)). 웹 채팅 화면이 필요할 때만 이 문서를 따라 하세요.
**먼저 README 의 2장(설치)을 끝내고 모델 서버가 켜져 있어야 합니다.**

## 1. Open WebUI 켜기

```bash
WEBUI_PORT=3200 ./webui.sh      # 기본 포트는 3000 입니다
```

- 이미 3000 포트에서 Open WebUI 를 쓰고 있다면 위처럼 다른 포트를 지정하세요 (충돌합니다).
- 처음에는 최신 Open WebUI 를 받느라 몇 분 걸립니다. 데이터는 이 폴더의 `.webui/` 에 저장됩니다.
- 브라우저에서 `http://127.0.0.1:3200` 을 열고 관리자 계정을 만듭니다 (처음 가입한 계정이 관리자).

## 2. 도구와 프리셋 등록

```bash
.venv/bin/python openwebui/install.py --webui-url http://127.0.0.1:3200 --email 내이메일 --password '내비밀번호'
```

API 키를 쓰려면 `--email/--password` 대신 `--api-key 키`. 이 명령은 다시 실행해도 안전합니다 (있으면 갱신).
등록되는 것: 모델 서버 연결, 도구 `al_alloy_design`, 모델 프리셋 **Al Alloy Design**.

## 3. 사용

채팅 화면에서 모델로 **Al Alloy Design** 을 고르고 요구사항을 입력합니다.
설계는 몇 분 걸리고, 그동안 `design_alloy 실행 중...` 이 표시됩니다.

## 4. 알아둘 점

- 프리셋의 도구는 화면에서만 자동으로 켜집니다. API 로 호출할 때는 요청에 `tool_ids: ["al_alloy_design"]` 을 넣어야 합니다.
- 설계 품질은 CLI 와 같습니다 (같은 설계 루프를 실행합니다). 작은 모델에서 끝까지 돌지 않는 문제도 같습니다.
- 끄기: 터미널에서 `Ctrl+C`. 삭제: `rm -rf .webui`.
