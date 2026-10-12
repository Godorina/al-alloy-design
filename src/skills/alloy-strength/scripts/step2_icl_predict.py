"""Score strength candidates: ICL prediction of the target property (validated as condition B
in icl/validate.py), CatBoost predictions of UTS/YTS/EL, measured-range flags, the nearest
measured alloy and the spec constraints. The only scoring script of this skill.

For each candidate, Qwen reads the K measured conditions of the spec series (default 6xxx) nearest to it, each with its
measured value and an out-of-fold CatBoost prediction (ml_prediction_MPa), plus the saved
CatBoost prediction for the candidate, and predicts the target. Repeated over `draws`
different example sets: icl = mean, icl_spread = std. UTS/YTS named by the user are predicted
by ICL; EL is always CatBoost-only. Results carry icl = {"UTS": .., "YTS": ..}; data follow the saved model
(ml_model/spec.json).
Diversity (rounds 1-3): what each candidate changed versus its parent example is recomputed
(step1, same spec; changes <= 0.02 wt% are copy noise). Candidates beyond the Si-alone or
same-lever cap, or with an unknown parent, are dropped before any Qwen call. --final skips the check.
Constraints: <P>_min is judged on the ICL prediction of P (ML only if P was not predicted);
EL_min uses the upper end of its ML 80% error range. Ranking: in support and no violation first,
then the ICL value of the first target (direction of its objective).

Usage:
  step2_icl_predict.py --spec '<spec JSON>' --candidates '<JSON list>' [--target UTS,YTS] [--draws 4] [--final]

Needs icl/ml_model/oof_<target>.json (made once by a human: icl/validate.py oof).
"""
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from step0_domain import PROCESS, flags, nearest, threshold
from step1_examples import examples_for
from step0_checks import SERIES, STRENGTH, check_spec, emit, fail, load_spec, normalize_candidate

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "icl"))
import core  # noqa: E402
import step0_data as sd  # noqa: E402

URL = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8080")  # OpenAI-compatible server, without /v1
MODEL = os.environ.get("LLM_MODEL", "local")
SLOTS = int(os.environ.get("LLM_SLOTS", "2"))  # parallel requests the server accepts
MAX_CANDS = 8
MIN_CHANGE = 0.02  # wt%; smaller differences from the parent are copy noise, not a change
DISAGREE = {"UTS": 25.0, "YTS": 25.0, "EL": 3.0}  # |icl - ml| above this -> "check"
NOTE = "ICL predictions by Qwen from measured examples + CatBoost hint; not measurements"


@lru_cache(maxsize=3)
def load_conditions(target: str, series: str = "6xxx"):
    ver = json.loads((core.ML_MODEL / "spec.json").read_text())["targets"][target]["data"]
    return ver, core.load(ver, target, series)[2]


@lru_cache(maxsize=3)
def model(target: str) -> dict:
    return joblib.load(core.ML_MODEL / f"catboost_{target}.joblib")


def ml_all(v: dict) -> dict:
    """CatBoost prediction of every property for a normalized candidate."""
    row, _ = sd.strength_row(v)
    out = {}
    for t in core.TARGETS:
        b = model(t)
        out[t] = round(float(b["model"].predict(b["imputer"].transform(pd.DataFrame([row])[b["columns"]]))[0]), 1)
    return out


def saved_hints(target: str, ver: str, series: str = "6xxx") -> dict:
    f = core.ML_MODEL / f"oof_{target}.json"
    if not f.exists():
        fail(f"missing {f.name}; a human must run icl/validate.py oof first")
    h = json.loads(f.read_text())
    if h.get("data") != ver:
        fail(f"{f.name} was built on {h.get('data')} data, model uses {ver}; rerun validate.py oof")
    if series not in h["hints"]:
        fail(f"{f.name} has no {series} hints; a human must rerun icl/validate.py oof")
    return h["hints"][series]


def _el_errors(series: str) -> list[float]:
    """Absolute OOF EL errors for non-nominal measured conditions in one series."""
    ver, cond = load_conditions("EL", series)
    hints = saved_hints("EL", ver, series)
    measured = cond[~cond.source.isin(sd.NOMINAL_SOURCES)]
    return [abs(float(row.y) - hints[row.cid]) for row in measured.itertuples()]


@lru_cache(maxsize=6)
def el_q80(series: str = "6xxx") -> float:
    """The 80th-percentile EL OOF error; use every measured series only when needed."""
    errors = _el_errors(series)
    if len(errors) < 30:
        errors = [error for name in SERIES for error in _el_errors(name)]
    return float(np.quantile(errors, 0.8))


def build_requests(spec: dict, cands: list, target: str, draws: int = 4, k: int = 8, hints=None):
    series = spec.get("series", "6xxx")
    ver, cond = load_conditions(target, series)
    hints = saved_hints(target, ver, series) if hints is None else hints
    parents = {e["id"]: e for e in examples_for(spec, 30)["examples"]}
    pool = np.arange(len(cond))
    reqs, meta = [], []
    for i, c in enumerate(cands, 1):
        cid = (c.get("id") if isinstance(c, dict) else None) or f"C{i}"
        v, why = normalize_candidate(c, spec)
        if v is None:
            meta.append({"id": cid, "error": why})
            continue
        ml = ml_all(v)
        parent = parents.get(v["parent"])
        q = pd.Series({**{e: v["composition"].get(e, 0.0) for e in core.solutes(series)},
                       **{p: v["process"].get(p) for p in core.PROCESS},
                       "temper": v["temper"], "route": v["route"]})
        ext = pd.concat([cond, q.to_frame().T], ignore_index=True)
        ext.attrs = cond.attrs  # concat drops attrs; distances() needs the series
        d = core.distances(ext, len(ext) - 1, pool)
        ranked = [(int(pool[j]), float(d[j])) for j in np.lexsort((pool, d))[:max(16, k)]]
        fl = flags(v, series)
        meta.append({"id": cid, "parent": v["parent"], "target": target, "data": ver, "series": series,
                     "composition": {e: round(x, 3) for e, x in v["composition"].items()},
                     "temper": v["temper"], "route": v["route"],
                     "process": {p: round(float(x), 2) for p, x in v["process"].items()},
                     "parent_measured": (None if parent is None else
                                         {"value": parent["measured"][target],
                                          "value_class": "nominal" if parent["source"] in sd.NOMINAL_SOURCES else "measured"}),
                     "ml": ml, "in_support": not fl, "flags": fl,
                     "nearest_measured": nearest(v["composition"], v["temper"], series)})
        for draw, sel in enumerate(core.draw_sets(cid, ranked, k, draws)):
            ctx = [{"id": cond.cid[j], "features": core.features(cond.iloc[j], hints[cond.cid[j]], "catboost", series),
                    "target": round(float(cond.y[j]), 1)} for j, _ in sel]
            text = core.prompt(ctx, core.features(q, ml[target], "catboost", series), True, "catboost", target, series)
            reqs.append({"id": cid, "draw": draw, "text": text})
    return reqs, meta


def ask(text: str) -> float:
    body = {"model": MODEL, "messages": [{"role": "user", "content": text}], "temperature": 0, "max_tokens": 128,
            "chat_template_kwargs": {"enable_thinking": False}}
    return core.ask(URL, body, timeout=120)[1]


def aggregate(reqs: list, meta: list, ask_fn=ask) -> list:
    def one(r):
        try:
            return ask_fn(r["text"]), None
        except Exception as e:  # one bad answer must not sink the other draws
            return None, f"{type(e).__name__}: {e}"[:120]
    with ThreadPoolExecutor(SLOTS) as ex:
        outs = list(ex.map(one, reqs))
    got = {}
    for r, (p, err) in zip(reqs, outs):
        got.setdefault(r["id"], []).append((p, err))
    res = []
    for m in meta:
        if "error" in m:
            res.append(m)
            continue
        vals = [p for p, _ in got.get(m["id"], []) if p is not None]
        errs = [e for _, e in got.get(m["id"], []) if e]
        icl = round(float(np.mean(vals)), 1) if vals else None
        r = dict(m, icl=icl, icl_spread=round(float(np.std(vals)), 1) if vals else None,
                 draws_ok=len(vals), errors=errs[:3],
                 icl_minus_ml=round(icl - m["ml"][m["target"]], 1) if vals else None)
        r["check"] = bool(vals) and abs(r["icl_minus_ml"]) > DISAGREE[m["target"]]
        res.append(r)
    return res


def levers(v: dict, parent: dict) -> set:
    """What changed from the parent: 'Si+', 'Cu-', ... and 'heat' for any process change."""
    c, p = v["composition"], parent["composition"]
    out = {f"{e}{'+' if c.get(e, 0.0) > p.get(e, 0.0) else '-'}" for e in set(c) | set(p)
           if abs(c.get(e, 0.0) - p.get(e, 0.0)) > MIN_CHANGE}
    if any(abs(float(v["process"].get(k) or 0) - float(parent["process"].get(k) or 0)) > 1e-6 for k in PROCESS):
        out.add("heat")
    return out


def diversity_drops(spec: dict, cands: list, parents: dict | None = None) -> list:
    """parents: id -> step1 example; default today's examples (prefix of any k <= 30). A grader passes the ones the
    run saw, because the examples change when the data does."""
    parents = parents or {e["id"]: e for e in examples_for(spec, 30)["examples"]}
    valid, dropped = [], []
    for i, c in enumerate(cands, 1):
        v, _ = normalize_candidate(c, spec)
        if v is None:
            continue  # rejected later with its own reason
        cid = c.get("id") or f"C{i}"
        if v["parent"] not in parents:
            dropped.append((i - 1, f"parent {v['parent']!r} is not a step1 example id (M1..)"))
            continue
        valid.append((i - 1, levers(v, parents[v["parent"]])))
    while True:
        cap = max(2, len(valid) // 2)
        seen, si_alone, round_drops = {}, 0, []
        for i, lv in valid:
            if spec.get("series", "6xxx") == "6xxx" and lv in ({"Si+"}, {"Si-"}):
                if si_alone:
                    round_drops.append((i, "changes Si alone; at most 1 may"))
                    continue
                si_alone += 1
            over = next((lever for lever in sorted(lv - {"heat"}) if seen.get(lever, 0) >= cap), None)
            if over:
                round_drops.append((i, f"changes {over}; at most {cap} may"))
                continue
            for lever in lv - {"heat"}:
                seen[lever] = seen.get(lever, 0) + 1
        if not round_drops:
            return dropped
        dropped.extend(round_drops)
        dropped_ids = {i for i, _ in round_drops}
        valid = [(i, lv) for i, lv in valid if i not in dropped_ids]


def diversity_problems(spec: dict, cands: list, parents: dict | None = None) -> list:
    return [f"{(cands[i].get('id') if isinstance(cands[i], dict) else None) or f'C{i + 1}'}: {reason}"
            for i, reason in diversity_drops(spec, cands, parents)]


def targets_of(spec: dict) -> list:
    """Named UTS/YTS properties; EL is ML-only, and UTS is the empty-spec default."""
    named = [o.get("property") for o in spec.get("objectives", []) if isinstance(o, dict)]
    named += [k[:-4] for k in (spec.get("constraints") or {}) if k.endswith("_min")]
    return list(dict.fromkeys(t for t in named if t in core.TARGETS and t != "EL")) if named else ["UTS"]


def score(spec: dict, cands: list, targets: list, draws: int = 4, k: int = 8, hints=None, ask_fn=ask) -> list:
    """ICL for every target (each with its own measured examples), merged per candidate:
    icl / icl_spread / icl_minus_ml / draws_ok become {target: value}; check lists the
    targets where ICL and ML disagree."""
    if not targets:
        _, meta = build_requests(spec, cands, "UTS", 0, k, {})
        return [m if "error" in m else dict(m, icl={}, icl_spread={}, icl_minus_ml={}, draws_ok={}, check=[], errors=[])
                for m in meta]
    per = {}
    for t in targets:
        reqs, meta = build_requests(spec, cands, t, draws, k, None if hints is None else hints[t])
        per[t] = aggregate(reqs, meta, ask_fn)
    out = []
    for rows in zip(*(per[t] for t in targets)):
        if "error" in rows[0]:
            out.append(rows[0])
            continue
        r = {k_: v for k_, v in rows[0].items() if k_ not in ("target", "data")}
        for key in ("icl", "icl_spread", "icl_minus_ml", "draws_ok"):
            r[key] = {t: x[key] for t, x in zip(targets, rows)}
        r["check"] = [t for t, x in zip(targets, rows) if x["check"]]
        r["errors"] = [e for x in rows for e in x["errors"]][:3]
        out.append(r)
    return out


def finish(spec: dict, targets: list, res: list) -> dict:
    """Constraint violations (ICL where predicted, else ML) and ranking by the first target's ICL."""
    out, rejected = [], []
    for r in res:
        if "error" in r:
            rejected.append(r)
            continue
        r = dict(r)
        el = r["ml"].get("EL")
        if el is not None:
            q80 = el_q80(spec.get("series", "6xxx"))
            r["el_range"] = [round(el - q80, 1), round(el + q80, 1)]
        viol = []
        for k, lim in (spec.get("constraints") or {}).items():
            if k.endswith("_min"):
                p = k[:-4]
                if p == "EL" and el is not None:
                    lo, hi = r["el_range"]
                    if hi < lim:
                        viol.append(f"EL {hi} < {k} {lim} (ML range)")
                    elif lo < lim <= hi:
                        r["check"] = [*r["check"], "EL"]
                    continue
                icl = r["icl"].get(p)
                val, src = (icl, "ICL") if icl is not None else (r["ml"].get(p), "ML")
                if val is not None and val < lim:
                    viol.append(f"{p} {val} < {k} {lim} ({src})")
            elif k.endswith("_max") and r["composition"].get(k[:-4], 0.0) > lim:
                viol.append(f"{k[:-4]} {r['composition'][k[:-4]]} > {k} {lim}")
        out.append(dict(r, violations=viol))
    first = targets[0] if targets else "UTS"
    sign = next((-1 if o.get("direction") == "minimize" else 1 for o in spec.get("objectives", [])
                 if o.get("property") == first), 1)
    out.sort(key=lambda r: (not (r["in_support"] and not r["violations"]),
                            -sign * (r["icl"].get(first) if r["icl"].get(first) is not None else r["ml"].get(first, -1e9 * sign))))
    return {"results": out, "rejected": rejected}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--target", help="comma list, e.g. UTS,YTS (default: every strength property in the spec)")
    ap.add_argument("--draws", type=int, default=4)
    ap.add_argument("--final", action="store_true", help="last scoring of the chosen set: no diversity check")
    a = ap.parse_args()
    spec = load_spec(a.spec)
    problems = check_spec(spec, STRENGTH)
    if problems:
        fail("spec problems", problems=problems)
    try:
        cands = json.loads(a.candidates)
    except json.JSONDecodeError as e:
        fail(f"--candidates is not valid JSON: {e}")
    cands = [cands] if isinstance(cands, dict) else cands
    if not isinstance(cands, list) or not 0 < len(cands) <= MAX_CANDS:
        fail(f"give 1-{MAX_CANDS} candidates per call")
    if not 1 <= a.draws <= 4:
        fail("--draws must be 1-4")
    targets = a.target.split(",") if a.target else targets_of(spec)
    objectives = [o.get("property") for o in spec["objectives"] if isinstance(o, dict)]
    if objectives and all(p == "EL" for p in objectives):
        fail(f"EL cannot be optimised: ML EL error ~{el_q80(spec.get('series', '6xxx')):.0f} %p "
             "(80th pct); give a strength objective and EL_min")
    if "EL" in targets:
        fail("EL is predicted by ML only: omit EL from --target")
    if not set(targets) <= set(core.TARGETS):
        fail(f"--target must be from {sorted(core.TARGETS)}")
    drops = [] if a.final else diversity_drops(spec, cands)
    dropped = {i for i, _ in drops}
    done = finish(spec, targets, score(spec, [c for i, c in enumerate(cands) if i not in dropped], targets, a.draws))
    emit({"note": NOTE, "targets": targets,
          "data": {t: load_conditions(t, spec.get("series", "6xxx"))[0] for t in targets},
          "disagree_threshold": {t: DISAGREE[t] for t in targets}, "distance_threshold": threshold(spec.get("series", "6xxx")),
          "dropped": [{"id": (cands[i].get("id") if isinstance(cands[i], dict) else None) or f"C{i + 1}",
                       "reason": reason} for i, reason in drops], **done})


if __name__ == "__main__":
    main()
