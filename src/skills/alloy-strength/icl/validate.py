"""WBM-style validation of ICL strength prediction: can Qwen predict measured 6xxx UTS
from measured examples in its context, and does it beat the ExtraTrees surrogate?

Protocol: 5-fold GroupKFold over measured 6xxx conditions by composition. Per query and
condition, K context examples from the other folds; draw 0 = top-K, draws 1.. = seeded
K-subsets of the top --ctx-pool. temperature 0, max_tokens 128, thinking off.
  A  composition+process distance, no surrogate in the prompt
  B  A + the ML prediction (--hint et|catboost) on every context and the query
Baselines: the fold ML model (query composition unseen), kNN (mean of the draw-0 contexts).

Usage (run from the project root; human-only, several hours of Qwen for the full plan):
  validate.py plan   --tag v1 [--data v1|v2|v3] [--k 8] [--draws 4] [--ctx-pool 16] [--target UTS|YTS|EL] [--hint et|catboost] [--conditions A,B] [--limit N]
  validate.py run    --tag v1 [--url http://127.0.0.1:18003] [--force]
  validate.py report --tag v1
  validate.py oof [--target T]        out-of-fold CatBoost hints for scripts/step2_icl_predict.py

--data v2 adds Mo et al. 2026 rows to the ExtraTrees data and the context pool; queries stay
the 502 v1 conditions with their v1 folds, so v1 and v2 reports are paired per query.
--data v3 also adds the reviewed paper extractions (export_rows.py -> lit_rows.parquet), paired the same way.

plan is immutable (refuses an existing tag); run only sends requests.jsonl from the plan and
skips ids that already have responses/<id>.json, so it resumes after an interruption.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

import joblib
import numpy as np

import core
from step0_checks import SERIES  # noqa: E402  (core puts ../scripts on sys.path)

OUT = core.ROOT / "runs" / "icl_strength"


def plan(a) -> None:
    out = OUT / a.tag
    if out.exists():
        sys.exit(f"{out} exists; plans are immutable, pick a new --tag")
    conds = a.conditions.split(",")
    if not set(conds) <= set(core.CONDITIONS) or a.k > a.ctx_pool:
        sys.exit(f"conditions must be from {sorted(core.CONDITIONS)} and --k <= --ctx-pool")
    u, X, cond = core.load(a.data, a.target, a.series)
    fold = core.fold_of(cond)
    queries = np.flatnonzero(cond.v1.to_numpy())
    if a.limit:
        queries = queries[np.linspace(0, len(queries) - 1, a.limit).astype(int)]
    cases, requests = [], []
    for f in range(5):
        qs = [q for q in queries if fold[q] == f]
        if not qs:
            continue
        print(f"fold {f}: fitting {a.hint} (1 outer + 5 inner)", file=sys.stderr)
        et_q, et_ctx, pool = core.fold_models(u, X, cond, fold, f, hint=a.hint)
        for q in qs:
            row = cond.iloc[q]
            for c in conds:
                show_et = core.CONDITIONS[c]
                d = core.distances(cond, q, pool)
                order = np.lexsort((pool, d))[:a.ctx_pool]  # ties broken by condition index
                ranked = [(int(pool[i]), float(d[i])) for i in order]
                for draw, sel in enumerate(core.draw_sets(f"{row.cid}~{c}", ranked, a.k, a.draws)):
                    ctx = [{"id": cond.cid[i],
                            "features": core.features(cond.iloc[i], et_ctx[i] if show_et else None, a.hint, a.series),
                            "target": round(float(cond.y[i]), 1)} for i, _ in sel]
                    text = core.prompt(ctx, core.features(row, et_q[q] if show_et else None, a.hint, a.series),
                                       show_et, a.hint, a.target, a.series)
                    ident = f"{row.cid}~{c}~{draw}"
                    requests.append({"id": ident, "body": {
                        "model": "qwen", "messages": [{"role": "user", "content": text}],
                        "temperature": 0, "max_tokens": 128,
                        "chat_template_kwargs": {"enable_thinking": False}}})
                    cases.append({"id": ident, "query": row.cid, "condition": c, "draw": draw,
                                  "fold": f, "label": round(float(row.y), 1),
                                  "temper": None if row.temper != row.temper else row.temper,
                                  "context_ids": [cond.cid[i] for i, _ in sel],
                                  "distances": [round(x, 4) for _, x in sel],
                                  "baselines": {"et": round(float(et_q[q]), 1),
                                                "knn": round(float(np.mean([cond.y[i] for i, _ in ranked[:a.k]])), 1)}})
    out.mkdir(parents=True)
    protocol = {"target": a.target, "data": a.data, **({"hint": a.hint} if a.hint != "et" else {}),
                **({"series": a.series} if a.series != "6xxx" else {}), "k": a.k, "draws": a.draws, "ctx_pool": a.ctx_pool, "conditions":
                {c: core.CONDITIONS[c] for c in conds}, "folds": "GroupKFold(5) by comp_key",
                "n_conditions": len(cond), "n_queries": len(queries), "et_training_rows": len(u),
                "temper_penalty": core.TEMPER_PENALTY, "route_penalty": core.ROUTE_PENALTY,
                "near_duplicate_holdout": {"wt": core.NEAR_WT, "MPa": core.NEAR_MPA},
                "retrieval_scaling": "z-score and process medians from the fold's pool (v2 pool includes Mo)",
                "temperature": 0, "max_tokens": 128, "thinking": False}
    (out / "plan.json").write_text(json.dumps({"protocol": protocol, "cases": cases}, ensure_ascii=False))
    (out / "requests.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in requests))
    print(f"planned {len(requests)} requests ({len(queries)} queries x {len(conds)} conditions x "
          f"{a.draws} draws) -> {out}")


def run(a) -> None:
    out = OUT / a.tag
    reqs = [json.loads(x) for x in (out / "requests.jsonl").read_text().splitlines()]
    if not a.force:  # :18003 is shared with other experiments; never pile onto a busy server
        try:
            with urllib.request.urlopen(a.url + "/slots", timeout=10) as r:
                slots = json.loads(r.read())
        except Exception as e:
            sys.exit(f"cannot read {a.url}/slots ({e}); check the server, or --force")
        if all(s.get("is_processing") for s in slots):  # this run uses one slot at a time
            sys.exit(f"all {len(slots)} slots busy; wait, or --force")
    resp = out / "responses"
    resp.mkdir(exist_ok=True)
    todo = [r for r in reqs if not (resp / f"{r['id']}.json").exists()]
    print(f"{len(reqs) - len(todo)} done, {len(todo)} to go", file=sys.stderr)
    for n, r in enumerate(todo, 1):
        rec = {"id": r["id"]}
        try:
            rec["content"], pred = core.ask(a.url, r["body"])
            rec.update(status="completed", prediction=pred)
        except Exception as e:
            rec.update(status="failed", error=f"{type(e).__name__}: {e}")
        (resp / f"{r['id']}.json").write_text(json.dumps(rec, ensure_ascii=False))
        if n % 50 == 0 or n == len(todo):
            print(f"{n}/{len(todo)}", file=sys.stderr)


def report(a) -> None:
    from scipy.stats import spearmanr
    out = OUT / a.tag
    p = json.loads((out / "plan.json").read_text())
    rec = {}
    for f in (out / "responses").glob("*.json"):
        r = json.loads(f.read_text())
        rec[r["id"]] = r
    rep = {"protocol": p["protocol"], "conditions": {}}
    for c in p["protocol"]["conditions"]:
        cs = [x for x in p["cases"] if x["condition"] == c]
        by_q = {}
        for x in cs:
            by_q.setdefault(x["query"], []).append(x)
        rows = []  # queries whose draws all completed
        failed = sum(rec.get(x["id"], {}).get("status") == "failed" for x in cs)
        for q, xs in by_q.items():
            preds = [rec.get(x["id"], {}).get("prediction") for x in xs]
            if all(v is not None for v in preds):
                rows.append((xs[0]["label"], float(np.mean(preds)), preds[0], float(np.std(preds)),
                             xs[0]["baselines"]["et"], xs[0]["baselines"]["knn"], xs[0]["temper"]))
        if not rows:
            rep["conditions"][c] = {"planned": len(cs), "failed": failed, "complete_queries": 0}
            continue
        y, ens, d0, sd, et, knn, tmp = map(list, zip(*rows))
        err = np.abs(np.array(ens) - y)
        t6 = [i for i, t in enumerate(tmp) if t == "T6"]
        rep["conditions"][c] = {
            "planned": len(cs), "answered": sum(x["id"] in rec for x in cs), "failed": failed,
            "llm_mean_of_draws": core.metrics(y, ens), "llm_draw0": core.metrics(y, d0),
            "et": core.metrics(y, et), "knn": core.metrics(y, knn),
            "llm_beats_et_fraction": round(float(np.mean(err < np.abs(np.array(et) - y))), 3),
            "T6_only": {"llm": core.metrics([y[i] for i in t6], [ens[i] for i in t6]),
                        "et": core.metrics([y[i] for i in t6], [et[i] for i in t6])} if len(t6) > 2 else None,
            "draw_spread_vs_error_spearman": (round(float(spearmanr(sd, err)[0]), 3)
                                              if p["protocol"]["draws"] > 1 and np.std(sd) > 0 else None)}
    (out / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1))
    print(json.dumps(rep["conditions"], ensure_ascii=False, indent=1))


def save_oof_and_model(target: str, version: str, spec: dict) -> None:
    """Persist matching OOF hints and the all-row CatBoost model for one target."""
    hints = {s: core.oof_hints(target, version, series=s) for s in SERIES}
    (core.ML_MODEL / f"oof_{target}.json").write_text(json.dumps(
        {"target": target, "data": version, "hint": "catboost", "n": {s: len(v) for s, v in hints.items()},
         "hints": hints}))
    u, X, _ = core.load(version, target)
    keep = np.ones(len(u), dtype=bool)
    imputer, model = core.fit_et(X, u[target].to_numpy(float), keep, "catboost")
    columns = list(X.columns)
    pred = float(model.predict(imputer.transform(X.iloc[[0]][columns]))[0])
    joblib.dump({"model": model, "imputer": imputer, "columns": columns}, core.ML_MODEL / f"catboost_{target}.joblib")
    spec["targets"][target] = {"data": version, "n_rows": len(u), "n_features": len(columns),
                               "check_pred_row0": pred}
    print(f"{target}: {sum(map(len, hints.values()))} conditions ({version}) and {len(u)}-row model", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["plan", "run", "report", "oof"])
    ap.add_argument("--tag")
    ap.add_argument("--out-dir", help="where <tag>/ goes (default runs/icl_strength)")
    ap.add_argument("--target", choices=sorted(core.TARGETS), help="default UTS (oof: all targets)")
    ap.add_argument("--data", choices=sorted(core.sd.DATA),
                    help="plan data (default v1), or the data to persist for oof")
    ap.add_argument("--series", choices=SERIES, default="6xxx", help="alloy series of queries and contexts")
    ap.add_argument("--hint", choices=sorted(core.HINTS), default="et",
                    help="ML model whose prediction conditions B/D show (catboost: ml_model/ settings)")
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--draws", type=int, default=4)
    ap.add_argument("--ctx-pool", type=int, default=16)
    ap.add_argument("--conditions", default="A,B")
    ap.add_argument("--limit", type=int, default=0, help="evenly spaced N queries (smoke tests)")
    ap.add_argument("--url", default="http://127.0.0.1:18003")
    ap.add_argument("--force", action="store_true", help="run even if the server looks busy")
    a = ap.parse_args()
    if a.out_dir:
        global OUT
        OUT = Path(a.out_dir).resolve()
    if a.mode == "oof":  # example hints for scripts/step2_icl_predict.py, on each saved model's data
        spec = json.loads((core.ML_MODEL / "spec.json").read_text())
        for t in ([a.target] if a.target else sorted(spec["targets"])):
            save_oof_and_model(t, a.data or spec["targets"][t]["data"], spec)
        (core.ML_MODEL / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n")
        return
    if not a.tag:
        ap.error("--tag is required for plan/run/report")
    a.target = a.target or "UTS"
    a.data = a.data or "v1"
    {"plan": plan, "run": run, "report": report}[a.mode](a)


if __name__ == "__main__":
    main()
