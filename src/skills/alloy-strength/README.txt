alloy-strength  —  알루미늄 합금 강도 역설계 스킬 (ICL, 전 계열)
======================================================================

한 줄 요약
  사용자가 "T6 압출재로 UTS 330 MPa 이상" 같은 목표를 주면, Qwen이 실측 합금 예시를
  보고 새 합금 후보를 제안하고, 후보의 UTS/YTS는 ICL(실측/공칭 예시 + ML 힌트), EL은 ML로 예측해
  한국어로 추천한다. 부식 자체 예측과 문헌 요약은 이 스킬 대상이 아니지만, 강도 요청에 부식이 있으면 가까운 합금의 실측 근거를 함께 보인다.

  대상 계열 (spec의 series, 기본 6xxx):
    2xxx, 5xxx, 6xxx, 7xxx, AlLi(Al-Li), cast_AlSi(주조 Al-Si)
    - 계열마다 그 계열의 실측 합금만 예시·실측 범위·최근접 합금에 사용
    - ML(CatBoost)은 모든 계열 데이터로 학습된 모델 하나를 공통으로 사용
    - 원소: 공통 9개(Mg Si Cu Fe Mn Cr Zn Ti Zr), 2xxx·AlLi는 Li·Ag 추가
    - 템퍼: T4~T8, H(가공경화, 5xxx), F
    - ICL 정확도 검증은 6xxx만 완료 (5장). 다른 계열은 아직 미검증
    - 실측이 적은 조합은 예시가 8개보다 적을 수 있음 (예: AlLi T8, 주조 T4의 YTS);
      실측이 하나도 없으면 step1이 오류로 알려줌
    - 후보 조성 한도: Li·Ag는 2xxx·AlLi만, 총 용질 7xxx 20% / 주조 30% / 그 외 15%,
      한 원소 주조 25% / 그 외 15%


1. 폴더 구성
----------------------------------------------------------------------
alloy-strength/
├── README.txt                  이 문서 (사람용, Qwen은 읽지 않음)
├── SKILL.md                    Qwen이 읽는 설명서: 절차, spec 형식, 답변 양식, 규칙
│
├── scripts/                    [Qwen 실행] 스킬 실행 중 run_skill_script로 부르는 스크립트
│   ├── step0_data.py             import 전용: 데이터 경로, ML 입력 64열, 후보 → ML 입력 행
│   ├── step0_checks.py           import 전용: spec·후보 검사(허용 원소·계열별 상한), JSON 출력
│   ├── step0_domain.py           import 전용: 실측 범위, 가장 가까운 실측 합금
│   ├── step1_examples.py         실측 예시 16개 선택 (LLM 없음)
│   ├── step2_icl_predict.py      후보 채점: ICL 예측 + ML 예측 + 범위 검사 (유일한 채점기)
│   └── step3_corrosion.py        요청했을 때만: 가까운 같은 상태의 부식 실측 근거(시험 범주·매질별)
│
└── icl/                        [공용 엔진 + 사람 전용 검증]
    ├── core.py                   ICL 공통 부품 (데이터, 예시 거리, 프롬프트, Qwen 호출)
    ├── validate.py               ICL 정확도 검증 실험 (사람만 실행, Qwen 수 시간)
    └── ml_model/                 저장된 ML 모델과 힌트
        ├── catboost_UTS.joblib     UTS 모델 (v3 데이터)
        ├── catboost_YTS.joblib     YTS 모델 (v3 데이터)
        ├── catboost_EL.joblib      EL 모델  (v3 데이터)
        ├── oof_UTS.json            실측 합금별 out-of-fold ML 예측 (ICL 예시에 붙는 힌트, 계열별)
        ├── oof_YTS.json            〃
        ├── oof_EL.json             〃
        └── spec.json               모델 설정 (CatBoost 800 iter, lr 0.05, depth 8, 입력 64열)


2. 실행 흐름 (사용자 요청 한 번)
----------------------------------------------------------------------
  [Qwen]   SKILL.md를 읽고 요청을 spec(JSON)으로 정리
           (계열·목표·제약·템퍼·가공, 말하지 않은 값은 "가정"에 기록; 7075 → 7xxx 등)
     ↓
  [스크립트] step1_examples.py --spec ...     → 실측 예시 16개 + 실측 범위(support)
     ↓
  [Qwen]   예시를 보고 후보 최대 8개 제안 (각 후보에 parent 예시 + 변경 이유)
     ↓
  [스크립트] step2_icl_predict.py --spec ... --candidates ...
           · 후보 다양성 검사: 위반 후보는 채점 전에 dropped로 돌려주고 다음 라운드에 다른 부모/레버로 교체
           · UTS/YTS 후보마다 비슷한 실측 합금 8개 + ML 힌트로 Qwen에게 물어 ICL 예측 (4회 평균); EL은 ML만 사용
           · CatBoost ML 예측(UTS/YTS/EL), 실측 범위 밖 flags, 가장 가까운 실측 합금, 제약 위반
     ↓  (2~3 라운드 반복)
  [스크립트] step2_icl_predict.py ... --final   → 반올림한 최종 후보 채점
     ↓
  [스크립트] 부식 요청이면 step3_corrosion.py ... → 가까운 합금·시험 {text, class}·실측값
     ↓
  [Qwen]   한국어 답변: 설계 목표 / 가정 / 후보표(ICL·ML·확인 필요) / 부식 근거 / 근거 / 주의

  부식 근거(5b)는 예측이 아니다. 기록 템퍼가 같거나 공정·라벨로 T6/T7/T4/F를 추정한 가까운 실측값만 보며,
  값 비교는 같은 시험 범주와 같은 매질 안에서만 한다. 공칭 JSM 등급은 실측값과 구분하고, 근거가 없으면
  후보마다 "데이터로 판단 불가"라고 쓴다.

  누가 무엇을 실행하나
    Qwen  : scripts/ 안의 파일만 (host의 run_skill_script 샌드박스, 셸 없음)
    사람  : icl/validate.py, tests/ (Qwen은 실행 불가)


3. 파일별 설명
----------------------------------------------------------------------
scripts/step0_domain.py   (import 전용, 모든 함수가 series 인자를 받음, 기본 6xxx)
  - data(series)   통합 강도 데이터 중 해당 계열·대기 환경 행
  - solutes(series) 계열의 원소 목록 (공통 9개 + 2xxx·AlLi는 Li·Ag)
  - ranges(temper, series) 템퍼별 실측 5~95% 범위 (용질 원소, 6xxx는 Mg:Si, 용체화/시효 온도·시간)
  - threshold()    "실측 합금과 너무 멀다"의 기준 거리 (최근접 거리의 95 백분위)
  - nearest(comp)  가장 가까운 실측 합금과 그 실측 강도
  - flags(cand)    실측 범위 밖이면 경고 문자열 (주 원소가 하한 미만이면 그 계열이 아님:
                   6xxx Mg·Si, 7xxx Zn·Mg, 2xxx Cu, 5xxx Mg, AlLi Li, 주조 Si)

scripts/step1_examples.py
  사용: step1_examples.py --spec '<spec JSON>' [--k 16]
  - spec의 series(기본 6xxx) 합금 중 목표 물성(첫 objective, 없으면 UTS)이 실측된 것만 사용
  - 같은 조건의 반복 측정은 중앙값으로 합침, 같은 조성은 최대 2개
  - 요청 가공 방식 합금과 그 외 합금을 번갈아 뽑음
    (각 그룹 안에서는 열처리 수치가 있는 것 먼저, 그다음 목표값에 가까운 순)
  - 출력: goal {property, value}, 예시 목록(M1, M2, ...), support 범위

scripts/step2_icl_predict.py
  사용: step2_icl_predict.py --spec '<spec>' --candidates '<JSON 목록>'
                             [--target UTS,YTS] [--draws 4] [--final]
  - --target 생략 시 spec의 UTS/YTS objectives와 <P>_min, 없으면 UTS (EL은 항상 ML)
  - 출력(후보별): icl / icl_spread {UTS/YTS: 값}, ml {UTS, YTS, EL}, check(ICL과 ML 차이가
    UTS·YTS 25 MPa 초과인 물성), flags, nearest_measured, violations, in_support
  - 제약 판정은 ICL 예측으로 (그 물성을 ICL로 안 했으면 ML로)
  - 정렬: 범위 안·위반 없음 먼저, 그다음 첫 목표 물성의 ICL 값
  - 다양성 규칙: 같은 방향의 같은 변경은 후보의 절반(최소 2)까지, (6xxx만) Si만 바꾼 후보는
    1개까지, 0.02 wt% 이하 변화는 변경으로 치지 않음
  - Qwen 주소: 환경변수 QWEN_URL (기본 http://127.0.0.1:18003)

icl/core.py   (step2_icl_predict.py와 validate.py가 함께 씀 → 검증과 실제 예측이 같은 방식)
  load(version, target, series)
                          데이터 로드. ML 학습용은 전 계열, "조건" 표(예시·문제)는 해당 계열만.
                          같은 조건의 반복 측정은 중앙값으로 합침
  solutes(series)         계열의 원소 목록 (6xxx는 검증 때와 같은 9개 그대로)
  fold_of / held_out / pool_of
                          검증용 조성 그룹 5-fold, 문제와 같은/거의 같은 합금 제외
  fit_et / fold_models    fold별 ML 모델 학습 (CatBoost 또는 ExtraTrees)
  oof_hints(target, ver, series=...)
                          out-of-fold ML 예측 (ml_model/oof_*.json의 원본)
  distances(cond, q, pool)
                          문제 합금과 후보 예시 간 거리 (조성 + 열처리, 표준화)
                          템퍼가 다르면 +100, 가공 방식이 다르면 +0.5
  draw_sets               예시 8개 뽑기: 1회차 = 가장 가까운 8개, 2~4회차 = 가까운 16개 중 무작위
  features / instruction / prompt
                          Qwen에게 보낼 프롬프트 (지시문 + 예시 8개 + 문제 합금 [+ ML 힌트])
  ask(url, body)          Qwen 호출, {"prediction": 숫자} 형식만 인정
  metrics(y, p)           MAE / RMSE / R²
  CONDITIONS              A = ML 힌트 없음(ICL), B = ML 힌트 있음(ML+ICL)

icl/validate.py   (사람 전용)
  "Qwen이 예시만 보고 실측 강도를 맞히나?"를 데이터의 실측 합금으로 검증.
  plan   문제 세트와 요청 파일 생성 (한 번 만들면 변경 불가)
  run    Qwen에 요청, responses/에 저장 (끊겨도 이어서 실행)
  report 채점
  oof    ml_model/oof_<물성>.json과 전체 행 CatBoost 모델을 함께 생성, 6개 계열 모두 {series: {cid: 힌트}} (step2가 필요로 함)
  주요 옵션: --target UTS|YTS|EL, --series 2xxx|5xxx|6xxx|7xxx|AlLi|cast_AlSi, --data v1|v2|v3,
            --hint catboost|et, --conditions A,B,
            --limit N, --k 8, --draws 4, --out-dir

icl/ml_model/
  catboost_*.joblib   전체 데이터로 학습한 최종 모델. 후보의 ML 예측과 ML 힌트에 사용.
  oof_*.json          실측 합금마다 "그 합금을 안 본 모델"의 예측. 예시에 붙이는 힌트라
                      정답이 새지 않도록 out-of-fold로 만듦. 계열별로 나뉘어 있음.
  spec.json           학습 설정, 데이터 버전, 입력 열, 모델 선택 근거(2026-09-24 비교).


4. 스킬 폴더 밖 관련 위치 (프로젝트 루트 기준)
----------------------------------------------------------------------
  데이터       assets/strength_unified/output/     v1: 4개 출처 통합 강도 데이터
              assets/strength_unified/output_v2/  v2: v1 + Mo et al. 2026
              runs/literature/extracted/lit_rows.parquet  v3: v2 + 검수된 논문 행 (step0_data.table에서 결합)
  샌드박스      src/mcp/host/mcp_host.py  (run_skill_script: scripts/만 실행)
  테스트       tests/alloy_strength/test_strength_skill.py 스크립트·엔진·샌드박스 자체 검사 (Qwen 없음)
              tests/alloy_strength/icl_eval/ ML vs ICL vs ML+ICL 성능 평가 (<계열>_<물성> 폴더)
              tests/alloy_strength/agent_eval/test_agent_eval.py 세션 채점기 자체 검사 (Qwen 없음)
  실행: .venv/bin/python tests/alloy_strength/test_strength_skill.py


5. 검증 결과 요약 (tests/alloy_strength/icl_eval, 6xxx, 물성별 100개)
----------------------------------------------------------------------
  기존 평가(v1/v2, 2026-09-25) MAE (UTS·YTS는 MPa, EL은 %p)
                                      ML      ICL     ML+ICL
    UTS                            26.5    26.2    23.6
    YTS                            25.7    28.2    25.6
    EL                              2.5     3.0     2.9
  - 실측 쿼리만 보면 EL의 ML+ICL−ML 절대오차 차이는 +1.18 %p, 95% CI [0.31, 2.07]이다.
    따라서 EL은 ICL을 쓰지 않고 ML과 80% 오차 범위(6xxx v3에서 ±6.156 %p)만 보인다.
  - ICL 단독(힌트 없음)은 ML을 이기지 못함 → 스킬은 ML 힌트를 함께 주는 방식(조건 B) 사용.
  - v3 재평가(2026-09-28, 조건 B만)는 아래와 같다. 실측 구간의 v3−기존 ML+ICL 차이의
    95% CI 하한이 모두 0 이하라서, v3 전환이 유의하게 나빠졌다고 볼 근거는 없다.

    물성   실측 ML+ICL MAE(기존 → v3)   v3−기존 95% CI
    UTS    24.3 → 23.1 MPa               [-3.720, 1.152]
    YTS    30.4 → 28.2 MPa               [-6.414, 1.189]

  자세한 표: tests/alloy_strength/icl_eval/summary.md (기존) 및 summary_v3.md (v3 조건 B).


6. 변경 메모
----------------------------------------------------------------------
  2026-09-25  icl/core.py distances(): 한 번도 측정되지 않은 공정 열(YTS 데이터의
              ss_time_h)이 NaN으로 남아 모든 거리가 NaN → 예시가 번호순으로 뽑히던 버그 수정.
              값이 없는 열은 0으로 채워 거리에 영향 없게 함. UTS·EL은 영향 없었음.
  2026-09-25  전 계열 지원: spec.series (2xxx/5xxx/6xxx/7xxx/AlLi/cast_AlSi), H·F 템퍼,
              Li·Ag 원소, 계열별 ML 힌트. 6xxx는 프롬프트·문제 세트·힌트가 바이트 단위로
              이전과 같음을 확인 (UTS 평가 800건 재생성 비교) → 6xxx 검증 결과 그대로 유효.
  2026-09-27  기본 표를 v3(v2 + 검수된 논문 행)로 통일하고 UTS/YTS/EL 모델·OOF 힌트를 같은 표에서 재학습.
              EL은 실측 구간에서 ICL이 ML보다 나빠 ML 전용으로 고정. 부식 값은 설계 대상이 아니라
              같은 템퍼의 가까운 실측 근거만 표시한다.
  2026-09-28  v3 UTS/YTS 조건 B 재평가(각 100 query × 4 draw)를 완료. 기존 실측 query와 짝지은
              비열화 기준을 통과했으며, 원래 결과 폴더와 응답은 보존했다.
