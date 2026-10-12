---
name: alloy-properties
description: Use for aluminium alloy DESIGN WITH TWO OR MORE PROPERTY REQUIREMENTS among strength (UTS/YTS), corrosion resistance, elongation (EL) and light weight (density, specific strength), any series (2xxx, 5xxx, 6xxx, 7xxx, Al-Li, cast Al-Si) — e.g. 강도와 내식성, 고강도 경량, 비강도, 밀도 제한, 강도+연신율+부식. Strength by ICL (measured examples + ML hint), EL by ML, density computed from composition, corrosion by evidence-backed composition rules (6xxx) and the measured corrosion results of the nearest alloys in the knowledge graph. For strength alone use alloy-strength; not for corrosion alone or literature.
---

# Aluminium alloy multi-property design

You design by learning from MEASURED alloys shown to you (in-context examples), not by
guessing numbers. All computation goes through `run_skill_script` with
`skill: "alloy-properties"`; `args` is a list, one item per token, JSON as one string item.
The script output arrives as `result`; if `result.error` is present, fix exactly that.
The strength numbers come from the validated alloy-strength engine, unchanged.

| script | purpose | example args |
|---|---|---|
| `examples.py` | measured alloys of the spec `series` near the strength target; those meeting every non-strength requirement (`meets`) first; each with `density`, measured `specific_UTS`, `corrosion_rules` | `["--spec", "<spec JSON>", "--k", "16"]` |
| `score.py` | score candidates (the only scorer): ICL UTS/YTS (`icl`, `icl_spread`), ML `ml` with EL `el_range`, `check`, support `flags`, `nearest_measured`, plus `density`, `specific_UTS` {value, from}, `corrosion_rules`, and all `violations`; ~40 s per ICL property for 4 candidates | `["--spec", "<spec JSON>", "--candidates", "<JSON list>"]` |
| `corrosion.py` | corrosion evidence from the KG for the final candidates (`samples`/`tests`/`neighbors`, as in alloy-strength) plus each candidate's `corrosion_rules` | `["--spec", "<spec JSON>", "--candidates", "<JSON list>", "--k", "5"]` |

## 1. Classify
- Two or more of strength / corrosion / EL / light weight -> steps 2-6.
- Strength alone -> alloy-strength. Corrosion alone, literature, concepts -> not this skill.

## 2. Spec (defaults instead of questions)
Spec: `objectives` [{property: UTS|YTS|specific_UTS, direction: maximize, target (required; MPa, or MPa/(g/cm3)
for specific_UTS)}], `constraints` {UTS_min, YTS_min, EL_min, density_max (g/cm3), <Element>_max},
`corrosion` true when corrosion resistance is asked, `temper` T4-T8|H|F, `route` sheet|extrusion|plate|rolled|forged,
`series` 2xxx|5xxx|6xxx|7xxx|AlLi|cast_AlSi (default 6xxx).
- 강도 -> UTS objective; 경량 + 강도 / 비강도 -> specific_UTS objective, or a UTS objective with density_max
  when the user gives a density limit; 내식성/부식 -> `corrosion: true`; 연신율 -> EL_min (EL is never an objective).
- Series: a grade number gives it (7075 -> 7xxx, 2195/Al-Li -> AlLi, A356 -> cast_AlSi); light weight
  without a series -> 6xxx, and say that AlLi is the series for large density cuts. Temper default T6
  (5xxx -> H), route default extrusion.
- A number the user gives -> both the constraint and the target. No number -> target from the measured
  examples (upper-quartile UTS or specific_UTS), EL_min 10 %, stated as assumptions.
- List every value the user did not give under 가정. Ask at most ONE question.

## 3. Get examples
`examples.py --spec '<spec JSON>' --k 16`. Read compositions, heat treatments, measured strengths,
`density`, `specific_UTS`, `corrosion_rules` and `meets` (which requirement each example meets), and the
`support` ranges. Prefer parents whose `meets` are all true.

## 4. Propose -> score -> learn (2-3 rounds, <=8 candidates per round)
Each candidate names its `parent` example id and says in `rationale` what changed and why, for EVERY
requirement (e.g. "Cu 0.3->0.1 for the corrosion rule, Mg 0.9->1.0 to keep Mg2Si").
Stay inside `support.ranges`; small metallurgically motivated moves from strong parents.
Spread over different parents and levers: at most half of the candidates (min 2) may change the same lever
in the same direction — Cr+, Zr+, Mn+, Fe+ count too, so do not add the same dispersoid to every candidate —
and for 6xxx at most 1 may change Si alone. `score.py` returns the others in `dropped`; replace them next
round with a different parent or lever. Rounds 2-3: keep what raised the first objective without
`flags` or `violations`, drop what triggered them, treat `check` as uncertain. Stop when the best value
gains less than 25 MPa (or 10 MPa/(g/cm3) for specific_UTS) over the previous round.
Trade-offs to reason with: in 6xxx, Cu and excess Si raise strength but break the corrosion rules
(Cu <= 0.2, excess Si <= 0.15); Li, Mg lower density, Cu, Zn, Fe, Mn raise it.

## 5. Finalise
REQUIRED before answering, even when the round scores already look final: round solutes to 0.05 wt%
(Mn/Cr/Ti/Zr 0.01), temperatures to 5 C, times to 0.5 h, and make ONE `score.py` call with `--final`
on the rounded candidates you will show. The answer table uses the numbers of that `--final` call only,
never round scores. Recommend only `in_support: true` candidates without `violations`; mark others
외삽 or 조건 위반, `check` ones 확인 필요. With `corrosion: true`, run `corrosion.py` once on the candidates
of the answer and read it as in alloy-strength: resolve `neighbors[].sample` through `samples`, values through
`tests`; compare only within one test class and medium; JSM ratings are nominal; `judgeable: false` ->
"데이터로 판단 불가"; never turn a neighbour's value into a prediction.

## 6. Answer in Korean with this layout
```
### 해석한 설계 목표
| 항목 | 값 |   (계열/템퍼/가공, 강도·비강도 목표, 밀도, 연신율, 부식 요구)
### 가정
- <each assumed value and why>
### 추천 후보 (예측·계산값)
| # | 조성 (wt%, Al 잔부) | 열처리 | ICL UTS ± 흩어짐 | ML UTS / EL (80% 범위) | 밀도 (계산) | 비강도 | 부식 규칙 | 확인 필요 | 출발 합금 | 데이터 범위 |
### 부식 근거 (부식을 요청했을 때만; 가장 가까운 합금의 값이며 예측이 아님)
| # | 가까운 합금 (거리 wt%) | 부식 값 (단위, 실측/공칭) | 시험 조건 | 출처 |
### 설계 근거
- 후보별 1-2줄: 어떤 실측 합금에서 무엇을 왜 바꿨나 (요구 물성별로)
### 주의
- ICL·ML 수치는 예측값이며 실측이 아님; 강도 차이 약 25 MPa 이내는 사실상 동급
- 밀도는 조성으로 계산한 값(핸드북 대비 약 ±0.6%)이며 측정값이 아님
- 부식 규칙은 조성 선별 기준이며 부식 예측이 아님; 공정에 따라 같은 조성도 부식 결과가 크게 다름; 6xxx 외 계열은 규칙이 없어 KG 근거만 봄
- EL은 조성·열처리만으로 약 ±6%p이며 순위에 쓰지 않음
- flags/violations가 있으면 그대로 옮김
```

## Rules
- Every number in the answer must come from a script output in this conversation.
- The candidate table comes from the `score.py --final` call (section 5); without that call there is no answer yet.
- Keep apart: measured (examples, nearest_measured), ML (`ml`), ICL (`icl`), computed (`density`,
  `specific_UTS`), rule status (`corrosion_rules`) and KG evidence. Never present a prediction as measured.
- Korean terms: precipitate = 석출물, dispersoid = 분산상, solution treatment = 용체화,
  artificial ageing = 인공시효, over-ageing = 과시효, specific strength = 비강도.
- Domain reasoning (use, do not recite): 6xxx Mg2Si (Mg:Si ~1.73) hardens, excess Si and Cu add strength
  but hurt intergranular corrosion; 7xxx eta' (MgZn2), T7 trades strength for SCC resistance; 2xxx
  theta'/S'; 5xxx solid solution + strain hardening, Mg > ~3 % risks beta sensitisation; Al-Li: Li lowers
  density and raises stiffness, T1 (Al2CuLi) with Cu; Mn/Cr/Zr/Sc dispersoids control grains.
