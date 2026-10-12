---
name: alloy-strength
description: Use for aluminium alloy MECHANICAL STRENGTH design or questions, any series (2xxx, 5xxx, 6xxx, 7xxx, Al-Li, cast Al-Si) — recommend compositions/heat treatment for target UTS/YTS/EL (강도, 인장강도, 항복강도, 연신율, 기계적 물성 설계/추천/예측). Proposes candidates by ICL for UTS/YTS (measured examples + ML hint) and ML for EL; with a corrosion requirement, adds the measured corrosion results of the nearest alloys from the knowledge graph. Not for corrosion alone or literature.
---

# Aluminium alloy strength design by in-context learning

You design by learning from MEASURED alloys shown to you (in-context examples), not by
guessing numbers. All computation goes through `run_skill_script` with
`skill: "alloy-strength"`; `args` is a list, one item per token, JSON as one string item.
The script output arrives as `result`; if `result.error` is present, fix exactly that.

| script | purpose | example args |
|---|---|---|
| `step1_examples.py` | measured alloys of the spec `series` near the target (the ICL examples) | `["--spec", "<spec JSON>", "--k", "16"]` |
| `step3_corrosion.py` | corrosion evidence from the al6xxx KG: each nearby measured (or nominal) sample and test appears once in `samples`/`tests`; candidate `neighbors` reference sample ids | `["--spec", "<spec JSON>", "--candidates", "<JSON list>", "--k", "5"]` |
| `step2_icl_predict.py` | score candidates (the only scorer): ICL prediction of named UTS/YTS properties from the nearest measured alloys + ML hint (`icl` / `icl_spread` = {property: value}); EL is CatBoost `ml` with `el_range` (80% error range), as are UTS/YTS values without ICL. Includes `check`, support `flags`, `nearest_measured`, and constraint `violations`; ~40 s per ICL property for 4 candidates | `["--spec", "<spec JSON>", "--candidates", "<JSON list>"]` |

## 1. Classify
- Design for strength targets -> steps 2-6.
- "How strong is composition X?" -> build a minimal spec and run `step2_icl_predict.py --final --target
  <the ICL properties asked, e.g. UTS,YTS; default UTS>` once; EL is ML-only. Answer with ICL where present, the ML prediction, the
  nearest measured alloy and flags. No examples needed.
- Strength design that also asks for corrosion resistance (내식성, 부식, SCC) -> steps 2-6 plus step 5b.
- Corrosion alone, literature, concepts -> not this skill (the kg tools answer those).

## 2. Spec (defaults instead of questions)
Spec: `objectives` [{property: UTS|YTS|EL, direction: maximize, target (required, MPa or %)}],
`constraints` {UTS_min, YTS_min, EL_min, <Element>_max}, `temper` T4-T8|H|F,
`route` sheet|extrusion|plate|rolled|forged, `series` 2xxx|5xxx|6xxx|7xxx|AlLi|cast_AlSi (default 6xxx),
optional `process_hint`.
- Series from the request: a grade number gives it (7075 -> 7xxx, 2024 -> 2xxx, 5083 -> 5xxx,
  2195/Al-Li -> AlLi, A356/cast -> cast_AlSi); none named -> 6xxx, stated as an assumption.
- Temper: T4-T8 for heat-treatable series; 5xxx is strain hardened -> `H` (or `F`), and its
  candidates carry no solution/ageing process.
- A number the user gives ("UTS 330 이상") -> both a UTS_min constraint and the UTS target.
- EL alone cannot be optimised: require a UTS or YTS objective and use EL only as `EL_min`.
- No number -> target from the measured examples (e.g. an upper-quartile measured UTS), stated
  as an assumption. Default temper T6 for "strength", route from the request (default extrusion).
- List every value the user did not give under 가정. Ask at most ONE question, only if the
  property to optimise is unclear.

## 3. Get examples
`step1_examples.py --spec '<spec JSON>' --k 16`. Read the measured compositions, heat treatments and
strengths, and the `support` ranges (the region where the model has data).

## 4. Propose -> score -> learn (2-3 rounds, <=8 candidates per round)
Round 1: propose up to 8 candidates. Each MUST name its `parent` example id (e.g. "M3") and state
in `rationale` what you changed and why (e.g. "raise Si 0.8->0.9 for more Mg2Si + excess Si").
Stay inside `support.ranges` (solutes, Mg:Si for 6xxx, ss/age temperatures and times); prefer small,
metallurgically motivated moves from strong examples over large jumps; keep minor elements few.
Make the candidates DIFFERENT: spread them over different parents and different levers
(main solutes of the series, Cu, Mn/Cr/Zr dispersoids, ageing temperature/time, solution temperature);
at most half of the candidates (min 2) may change the same lever in the same direction, and for 6xxx at
most 1 candidate may change Si alone. `step2_icl_predict.py` checks this against each `parent` and returns invalid
candidates in `dropped`; replace them next round with a different parent or lever (changes <= 0.02 wt% do not count).
Score them with ONE `step2_icl_predict.py` call; it predicts requested UTS/YTS properties by ICL and keeps EL as ML.
Rounds 2-3: learn from the scores — keep what raised `icl` of the first objective without `flags` or `violations`,
drop what triggered them, treat `check: true` (ICL and ML disagree) as uncertain, then propose
again. Stop early if a round brings no gain.
If the best ICL value improves by less than 25 MPa over the previous round (also 25 MPa when the first target is YTS),
there is no gain: go straight to section 5 without another round.

## 5. Finalise
Round solutes to 0.05 wt% (Mn/Cr/Ti/Zr may use 0.01), temperatures to 5 C, times to 0.5 h; score
the final set with one `step2_icl_predict.py --final` call. Recommend only `in_support: true` candidates; if you show others,
mark them 외삽; mark `check: true` candidates 확인 필요.

## 5b. Corrosion (only when the request names it)
Run `step3_corrosion.py` once only on the final candidates that will appear in the answer. Resolve each `neighbors[].sample` through `samples`, then each
value's test index through `tests` (`{text, class}`); judge by its measured values and `distance` (wt%). Compare values only when test
`class` and the medium named in `text` are the same. `neighbors[].state_match` is `temper` for a recorded matching temper or
`inferred` when its `state_basis` infers T6 from solution treatment + artificial ageing + `peak`, T7 from `over`, T4 from
solution treatment + natural ageing only, or F from `as-cast` without steps; print the latter as `(추정 템퍼)`. A nominal
rating (class `nominal`, JSM) is a specification grade, not a measurement. A candidate with `judgeable: false`
gets "데이터로 판단 불가" in the table (no values); a neighbour with `far: true` is not used to rank candidates. Never turn a neighbour's
value into a prediction for the candidate. Only a non-far neighbour with `state_match` is judgeable; otherwise say
"데이터로 판단 불가" and give the tool's reason. Put that exact phrase in each unjudgeable candidate's row; do not combine candidates into one statement.

## 6. Answer in Korean with this layout
```
### 해석한 설계 목표
| 항목 | 값 |   (템퍼/가공, 목표 강도, 제약, 공정 범위)
### 가정
- <each assumed value and why>
### 추천 후보 (예측값)
| # | 조성 (wt%, Al 잔부) | 열처리 | ICL 예측 ± 흩어짐 (물성별) | ML 예측 (EL은 x, 80% 범위 lo–hi) | 확인 필요 | 출발 합금 (실측/공칭 값) | 데이터 범위 |
### 부식 근거 (요청했을 때만; 가장 가까운 실측 합금의 값이며 예측이 아님)
| # | 가까운 합금 (거리 wt%) | 부식 값 (단위, 실측/공칭) | 시험 조건 | 출처 |
### 설계 근거
- 후보별 1-2줄: 어떤 실측 합금에서 무엇을 왜 바꿨나
### 주의
- ICL·ML 수치는 모두 예측값이며 실측이 아님; 강도 차이 약 25 MPa 이내는 사실상 동급
- `value_class: nominal`은 규격 공칭값이며 실측이라고 부르지 않음
- ICL과 ML이 크게 다르면(확인 필요) 실험으로 확인 필요; EL은 시험 조건에 따라 연구마다 크게 달라 조성·열처리만으로는 약 ±6%p이며, EL로 후보 순위를 매기지 않고 실측 EL은 같은 출처끼리만 비교
- 6xxx가 아닌 계열이면: ICL 정확도는 6xxx에서만 검증됨
- flags/violations가 있으면 그대로 옮김
```

## Rules
- Every number in the answer must come from a script output in this conversation.
- Korean terms: precipitate = 석출물 (never 침출물/침전물), dispersoid = 분산상,
  solution treatment = 용체화, artificial ageing = 인공시효, over-ageing = 과시효.
- Keep three kinds of numbers apart: measured (examples, nearest_measured), ML prediction
  (`ml`) and ICL prediction (`icl`). Never present a prediction as measured.
- Domain reasoning (use, do not recite), by series:
  - 6xxx: Mg2Si (Mg:Si ~1.73 by weight) is the main hardening phase; excess Si raises peak
    strength; Cu adds Q'/L precipitates and strength.
  - 7xxx: Zn and Mg form eta' (MgZn2) precipitates, the strongest Al alloys; Zn:Mg ~2-3; Cu raises
    strength and stress-corrosion resistance; T7 over-ageing trades strength for SCC resistance.
  - 2xxx: Cu (with Mg) forms theta'/S' precipitates; Mg raises strength and natural-ageing response
    (T4); Ag promotes Omega at high Cu:Mg.
  - 5xxx: non-heat-treatable; Mg in solid solution plus strain hardening (H tempers) gives strength;
    Mn refines grains; above ~3 % Mg beware beta-phase sensitisation.
  - Al-Li: Li lowers density and raises stiffness; delta' (Al3Li) and T1 (Al2CuLi) with Cu give strength.
  - cast Al-Si: Si sets castability (eutectic ~12.6 %); Mg (Mg2Si) and Cu give T6 strength; Fe forms
    brittle beta-AlFeSi that cuts elongation.
  - All: Mn/Cr/Zr/Sc form dispersoids that control grain structure; T6 = peak aged, T7 = over-aged
    (lower strength); higher/longer ageing past peak lowers strength.
