"""ICL strength prediction core: measured conditions, fold-safe ExtraTrees, retrieval, prompts.

Used by validate.py. Nothing here calls the LLM. Not runnable by Qwen (the host only runs
the skill scripts/ folder).

Leakage rules (same spirit as the WBM validation):
  - folds group measured conditions of one alloy series (6xxx by default) by composition (comp_key), so a query's
    composition never appears among its contexts or in the ExtraTrees that scores it
  - the ExtraTrees prediction shown for a context example comes from an inner fold
    model that never saw that example's composition either
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.impute import SimpleImputer
from sklearn.model_selection import GroupKFold

ROOT = Path(__file__).resolve().parents[4]  # project root (src/skills/<skill>/icl/x.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import step0_data as sd  # noqa: E402

V1_SOURCES = {"mendeley", "ji", "hu", "rec6"}  # the v1 table; later sources only grow the pool
MODELS = sd.DATA["v1"] / "models"
SOLUTES = sd.SOLUTES
PROCESS = sd.PROCESS
SERIES_NAME = {"AlLi": "Al-Li", "cast_AlSi": "cast Al-Si"}  # prompt wording; others as is (7xxx)
GROUP = ["comp_key", "temper", "route"] + sd.PROC_COLS  # identical measured condition
TEMPER_PENALTY = 100.0  # retrieval A/B: another temper ranks behind every same-temper example
ROUTE_PENALTY = 0.5  # retrieval A/B: same alloy, other route (sheet vs extrusion) ranks just behind
NEAR_WT, NEAR_MPA = 0.3, 1.0  # added-data condition this close to a query = likely a re-report
NEAR_Y = {"UTS": NEAR_MPA, "YTS": NEAR_MPA, "EL": 0.1}  # same test per target (MPa, MPa, %)
TARGETS = {  # target -> (what to predict, what a context target is); UTS is the original wording
    "UTS": ("ultimate tensile strength (UTS, MPa)", "measured UTS in MPa"),
    "YTS": ("yield strength (YTS, MPa)", "measured YTS in MPa"),
    "EL": ("elongation to fracture (EL, %)", "measured EL in %"),
}

INSTR = ("Predict the ultimate tensile strength (UTS, MPa) of the query 6xxx aluminium alloy "
         "condition. Features: composition in wt% (Al balance; 0 = not added or not reported), "
         "solution treatment temperature (C) and time (h), first artificial ageing temperature (C) "
         "and time (h) (null = not reported), temper and product route. Each context is a measured "
         "alloy condition and its target is the measured UTS in MPa. "
         'Return exactly {"prediction": finite_number}, no other text.\n')
ET_INSTR = ("et_prediction_MPa is an ExtraTrees surrogate prediction for that condition from a "
            "model that never saw that composition; compare it with the context targets to judge "
            "how far off the surrogate is near the query.\n")
ML_MODEL = Path(__file__).resolve().parent / "ml_model"  # saved CatBoost surrogates + spec.json
HINTS = {  # hint model -> (prompt key, instruction); the ET entry is the original, byte-identical
    "et": ("et_prediction_MPa", ET_INSTR),
    "catboost": ("ml_prediction_MPa",
                 "ml_prediction_MPa is a CatBoost surrogate prediction for that condition from a "
                 "model that never saw that composition; compare it with the context targets to judge "
                 "how far off the surrogate is near the query.\n"),
}
CONDITIONS = {"A": False, "B": True}  # name -> show the ML prediction in the prompt


def load(version: str = "v1", target: str = "UTS", series: str = "6xxx") -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(all rows with a measured `target` = ML training data (every series), their feature matrix,
    measured conditions of `series`).

    A condition is one (composition, temper, route, process) with repeated measurements
    merged to the median; `y` is the target (== UTS for UTS) and cond.attrs["target"] names it;
    its features are those of its first row. `v1` marks conditions
    with at least one v1-source row: in v2 these are exactly the v1 conditions (the v2
    table is the v1 rows followed by the Mo rows, so cids of v1 conditions do not move)."""
    u = sd.table(version)
    u = u[u[target].notna()].reset_index(drop=True)
    X = u[sd.ELEMS30 + sd.PROC_COLS].astype(float)
    t = u.temper.fillna("nan").astype(str)
    r = u.route.fillna("nan").astype(str).str.lower()
    X = X.assign(**{f"temper_{v}": (t == v).astype(float) for v in sd.TEMPERS},
                 **{f"route_{v}": (r == v).astype(float) for v in sd.ROUTES})
    six = u[(u.series == series) & (u.corr_env == 0)]
    g = (six.assign(_row=six.index).groupby(GROUP, dropna=False)
         .agg(row=("_row", "first"), UTS=("UTS", "median"), y=(target, "median"), n=(target, "size"),
              v1=("source", lambda s: bool(s.isin(V1_SOURCES).any()))).reset_index(drop=True))
    cond = u.loc[g.row].assign(UTS=g.UTS.to_numpy(), y=g.y.to_numpy(), n=g.n.to_numpy(),
                               row=g.row.to_numpy(), v1=g.v1.to_numpy())
    cond = cond.sort_values("row").reset_index(drop=True)
    cond.insert(0, "cid", [f"c{i:03d}" for i in range(len(cond))])
    cond.attrs["target"], cond.attrs["series"] = target, series
    return u, X, cond


def solutes(series: str = "6xxx") -> list[str]:
    """Composition features of a series: the 6xxx set plus Li/Ag for 2xxx and Al-Li."""
    return sd.solutes(series)


def fit_et(X: pd.DataFrame, y: np.ndarray, keep: np.ndarray, hint: str = "et"):
    """ML surrogate trained on rows `keep`: ExtraTrees with the production hyperparameters,
    or CatBoost with the settings of the saved ml_model/ models."""
    imp = SimpleImputer(strategy="median", keep_empty_features=True).fit(X[keep])
    if hint == "catboost":
        from catboost import CatBoostRegressor
        params = json.loads((ML_MODEL / "spec.json").read_text())["params"]
        return imp, CatBoostRegressor(**params).fit(imp.transform(X[keep]), y[keep])
    params = json.loads((MODELS / "surrogate_spec.json").read_text())["params"]
    return imp, ExtraTreesRegressor(**params).fit(imp.transform(X[keep]), y[keep])


def _group_folds(cond: pd.DataFrame, n: int, groups=None) -> np.ndarray:
    g = cond.comp_key if groups is None else groups
    n = min(n, g.nunique())  # added data from fewer papers than folds: one fold per paper
    if n < 2:
        return np.zeros(len(cond), int)
    out = np.empty(len(cond), int)
    for f, (_, te) in enumerate(GroupKFold(n).split(cond, groups=g)):
        out[te] = f
    return out


def fold_of(cond: pd.DataFrame, n: int = 5) -> np.ndarray:
    """GroupKFold by composition. v1 conditions get exactly their v1 folds; compositions
    that only exist in added data are split by paper (a composition follows the first paper
    it appears in, so it never spans two folds), and one shared with v1 follows v1."""
    v1 = cond.v1.to_numpy()
    out = np.empty(len(cond), int)
    out[v1] = _group_folds(cond[v1], n)
    known = dict(zip(cond.comp_key[v1], out[v1]))
    rest = np.flatnonzero(~v1)
    shared = cond.comp_key.iloc[rest].map(known)
    out[rest[shared.notna().to_numpy()]] = shared.dropna().astype(int).to_numpy()
    new = rest[shared.isna().to_numpy()]
    if len(new):
        c = cond.iloc[new]
        out[new] = _group_folds(c, n, groups=c.groupby("comp_key").lit_group.transform("first"))
    return out


def held_out(cond: pd.DataFrame, fold: np.ndarray, f: int) -> set:
    """Compositions kept away from fold f's queries: the fold itself, plus added-data (non-v1)
    conditions within NEAR_WT wt% on every solute and NEAR_MPA of a query's UTS (the same
    alloy re-reported with impurities left blank gets another comp_key)."""
    q = np.flatnonzero(fold == f)
    held = set(cond.comp_key.iloc[q])
    extra = np.flatnonzero(~cond.v1.to_numpy() & (fold != f))
    if len(extra):
        x = cond[solutes(cond.attrs.get("series", "6xxx"))].fillna(0.0).to_numpy(float)
        y = cond.y.to_numpy(float)
        tol = NEAR_Y[cond.attrs.get("target", "UTS")]
        near = ((np.abs(x[extra][:, None] - x[q][None]).max(-1) <= NEAR_WT)
                & (np.abs(y[extra][:, None] - y[q][None]) <= tol)).any(1)
        held |= set(cond.comp_key.iloc[extra[near]])
    return held


def pool_of(cond: pd.DataFrame, fold: np.ndarray, f: int) -> np.ndarray:
    """Context candidates for fold f's queries."""
    return np.flatnonzero((fold != f) & ~cond.comp_key.isin(held_out(cond, fold, f)).to_numpy())


def fold_models(u, X, cond, fold, f, inner: int = 5, hint: str = "et"):
    """For outer fold f: the outer model's prediction for every condition (held_out
    compositions removed), inner out-of-fold predictions for the pool, and the pool itself."""
    y = u[cond.attrs.get("target", "UTS")].to_numpy(float)
    held = held_out(cond, fold, f)
    imp, m = fit_et(X, y, ~u.comp_key.isin(held).to_numpy(), hint)
    xc = imp.transform(X.loc[cond.row])
    et_outer = m.predict(xc)
    pool = pool_of(cond, fold, f)
    et_ctx = np.full(len(cond), np.nan)
    inner_fold = fold_of(cond.iloc[pool], inner)
    for g in range(inner):
        idx = pool[inner_fold == g]
        out = held | set(cond.comp_key.iloc[idx])
        imp2, m2 = fit_et(X, y, ~u.comp_key.isin(out).to_numpy(), hint)
        et_ctx[idx] = m2.predict(imp2.transform(X.loc[cond.row.iloc[idx]]))
    return et_outer, et_ctx, pool


def oof_hints(target: str, version: str, hint: str = "catboost", series: str = "6xxx") -> dict:
    """cid -> ML prediction for every measured condition from a model that never saw its
    composition (composition-grouped 5-fold): the example hints for scripts/step2_icl_predict.py."""
    u, X, cond = load(version, target, series)
    fold = fold_of(cond)
    y = u[target].to_numpy(float)
    pred = np.full(len(cond), np.nan)
    for f in range(5):
        idx = np.flatnonzero(fold == f)
        imp, m = fit_et(X, y, ~u.comp_key.isin(held_out(cond, fold, f)).to_numpy(), hint)
        pred[idx] = m.predict(imp.transform(X.loc[cond.row.iloc[idx]]))
    return dict(zip(cond.cid, np.round(pred, 2).tolist()))


def distances(cond, q: int, pool: np.ndarray) -> np.ndarray:
    """Standardized composition+process distance, same temper and route ranked first."""
    sol = solutes(cond.attrs.get("series", "6xxx"))
    x = cond[sol + PROCESS].astype(float)
    x[sol] = x[sol].fillna(0.0)
    x[PROCESS] = x[PROCESS].fillna(x.iloc[pool][PROCESS].median()).fillna(0.0)  # never-measured column -> constant, adds 0
    p = x.to_numpy()
    mu, sd = p[pool].mean(0), p[pool].std(0)
    sd[sd == 0] = 1.0
    z = (p - mu) / sd
    d = np.linalg.norm(z[pool] - z[q], axis=1)
    return (d + TEMPER_PENALTY * (cond.temper.iloc[pool].to_numpy() != cond.temper.iloc[q])
            + ROUTE_PENALTY * (cond.route.iloc[pool].to_numpy() != cond.route.iloc[q]))


def draw_sets(qid: str, ranked: list, k: int, draws: int) -> list[list]:
    """Draw 0 is the top-k; the others are seeded k-subsets of `ranked` (reproducible)."""
    out = [ranked[:k]]
    for d in range(1, draws):
        seed = int.from_bytes(hashlib.sha256(f"{qid}|{d}".encode()).digest()[:8], "big")
        pick = np.random.default_rng(seed).choice(len(ranked), k, replace=False)
        out.append([ranked[i] for i in sorted(pick)])
    return out


def features(row, et: float | None = None, hint: str = "et", series: str = "6xxx") -> dict:
    f = {e: (0.0 if pd.isna(row[e]) else round(float(row[e]), 3)) for e in solutes(series)}
    f.update({p: (None if pd.isna(row[p]) else round(float(row[p]), 2)) for p in PROCESS})
    f["temper"] = None if pd.isna(row.temper) else str(row.temper)
    f["route"] = None if pd.isna(row.route) else str(row.route)
    if et is not None:
        f[HINTS[hint][0]] = round(float(et), 1)
    return f


def instruction(target: str = "UTS", series: str = "6xxx") -> str:
    what, ctx = TARGETS[target]
    return (INSTR.replace(TARGETS["UTS"][0], what).replace(TARGETS["UTS"][1], ctx)
            .replace("query 6xxx", "query " + SERIES_NAME.get(series, series)))


def prompt(contexts: list[dict], query: dict, show_et: bool, hint: str = "et", target: str = "UTS",
           series: str = "6xxx") -> str:
    body = {"contexts": contexts, "query_features": query}
    return instruction(target, series) + (HINTS[hint][1] if show_et else "") + json.dumps(body, ensure_ascii=False, separators=(",", ":"))


def metrics(y, p) -> dict:
    y, p = np.asarray(y, float), np.asarray(p, float)
    e = p - y
    return {"n": len(y), "MAE": round(float(np.abs(e).mean()), 1),
            "RMSE": round(float(np.sqrt((e ** 2).mean())), 1),
            "R2": round(float(1 - (e ** 2).sum() / ((y - y.mean()) ** 2).sum()), 3)}


def ask(url: str, body: dict, timeout: float = 600) -> tuple[str, float]:
    """POST one chat request to llama-server; (raw content, prediction) or ValueError unless the
    answer is exactly {"prediction": finite number}."""
    body = {"model": os.environ.get("LLM_MODEL", "local"), **body}
    req = urllib.request.Request(url + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        ch = json.loads(r.read())["choices"][0]
    content = ch["message"]["content"]
    if ch.get("finish_reason") != "stop":
        raise ValueError(f"finish_reason {ch.get('finish_reason')}")
    v = json.loads(content)
    if not (isinstance(v, dict) and set(v) == {"prediction"}
            and isinstance(v["prediction"], (int, float)) and np.isfinite(v["prediction"])):
        raise ValueError(f"expected exactly {{\"prediction\": number}}: {content[:60]}")
    return content, float(v["prediction"])
