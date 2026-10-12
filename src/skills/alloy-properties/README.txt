alloy-properties  —  알루미늄 합금 다물성 역설계 스킬 (강도 + 부식 + 연신율 + 경량)
======================================================================

한 줄 요약
  "T6 압출, UTS 350 이상, 내식성, 밀도 2.70 이하" 같은 두 가지 이상의 요구를 받아,
  Qwen이 실측 합금 예시를 보고 후보를 내고, 스크립트가 강도(ICL+ML), 연신율(ML),
  밀도·비강도(계산), 부식(조성 규칙 + KG 근거)을 붙여 순위를 매긴다.

1. 구조: 강도 엔진은 alloy-strength를 그대로 import (복사하지 않음)
----------------------------------------------------------------------
  scripts/props.py       import 전용: 밀도 계산, 부식 조성 규칙, 다물성 spec 검사, strength view
  scripts/examples.py    alloy-strength step1 예시(같은 id M1..M30)를 요구 충족 순으로 재정렬 + 물성 표시
  scripts/score.py       alloy-strength step2 채점(다양성·ICL·ML·범위·제약) + 밀도·비강도·부식 규칙·순위
  scripts/corrosion.py   alloy-strength step3 KG 부식 근거 + 후보별 부식 규칙

  strength view: spec에서 corrosion, density_max를 빼고 specific_UTS 목표를 UTS 목표
  (목표 x 2.70)로 바꾼 spec. 엔진은 이것만 본다. 그래서 강도 예측 정확도는 alloy-strength의
  검증(6xxx UTS MAE 약 23 MPa, README 5절)이 그대로 유효하다.
  주의: 이 폴더의 스크립트 이름은 엔진 모듈 이름(step0_*, step1_examples, step2_icl_predict,
  step3_corrosion, core)과 겹치면 안 된다. 이 폴더가 sys.path 맨 앞이라 엔진이 우리 파일을 import하게 된다.

2. 물성별 방법과 근거
----------------------------------------------------------------------
  강도 UTS/YTS  ICL (실측 예시 8개 + CatBoost 힌트, 4회 평균), alloy-strength 그대로
  연신율 EL     CatBoost + 80% 오차 범위, 제약(EL_min)으로만 사용 (ICL이 ML보다 나빠 검증으로 고정된 결정)
  밀도          조성의 비체적 혼합: 1/rho = sum(w_i / rho_i). Li는 유효 밀도 0.737 g/cm3
                (핸드북 2195/2090/8090로 맞춤, 맞추는 데 안 쓴 2099/2050/2196은 0.4% 이내,
                Li 없는 6061/6082/7075/2024/5083/A356은 0.6% 이내)
  비강도        UTS / 밀도 (ICL UTS, 없으면 ML)
  부식          6xxx만 조성 규칙: Cu <= 0.2 wt%, 과잉 Si = Si - Mg/1.73 - (Fe+Mn)/3 <= 0.15 wt%.
                근거: al6xxx KG v0.5.0 (2026-10-01 확인). 입계부식 실측 깊이 Cu 0.30-0.79 합금
                187-229 um vs Cu 없는 합금 32-152 um (20건); JSM 등급 중앙 과잉 Si Excellent -0.03 vs
                Good +0.16 (275건, 공칭). 규칙은 선별 기준이며 부식 예측이 아니다.
                다른 계열은 근거 있는 규칙이 아직 없어 KG 근거(corrosion.py)만 본다.

3. 아직 안 하는 것 (1차 범위 밖)
----------------------------------------------------------------------
  - CLM으로 예시 컨텍스트 거르기: 기계적 선택(examples.py)과 실측 hold-out 비교로 이길 때만 도입
  - 6xxx 외 계열의 부식 규칙 (7xxx SCC/T7, 5xxx Mg 예민화, 2xxx Cu): 계열별 KG 근거 확인 후 추가
  - 다목적 파레토 순위: 지금은 제약 통과 후 첫 목표(UTS, YTS 또는 specific_UTS) 순

4. 테스트
----------------------------------------------------------------------
  .venv/bin/python tests/alloy_properties/test_properties_skill.py   (Qwen 없음, Qwen은 가짜 함수로 대체)
