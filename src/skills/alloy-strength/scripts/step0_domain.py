"""Where the strength model has measured support, per alloy series (default 6xxx).

Computed from the strength training data (one series, air, all sources):
  - per-temper 5-95 % ranges of each solute (Mg:Si for 6xxx) and process parameters
  - a per-series standardized solute distance; threshold = 95th percentile of the
    leave-one-out nearest-neighbour distance among measured compositions of that series
  - the nearest measured alloy for any candidate (with its median measured strength)

Imported by step1_examples.py (support ranges) and step2_icl_predict.py (flags, nearest).
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

import step0_data as sd

MAJOR = {"6xxx": ("Mg", "Si"), "7xxx": ("Zn", "Mg"), "2xxx": ("Cu",), "5xxx": ("Mg",),
         "AlLi": ("Li",), "cast_AlSi": ("Si",)}  # below the measured range = not that series
PROCESS = sd.PROCESS
solutes = sd.solutes


MIN_ROWS_PER_TEMPER = 30  # fewer measured rows than this -> use all rows of the series for ranges


@lru_cache(maxsize=8)
def data(series: str = "6xxx") -> pd.DataFrame:
    u = sd.unified()
    u6 = u[(u.series == series) & (u.corr_env == 0)].copy()
    u6[solutes(series)] = u6[solutes(series)].fillna(0.0)  # unreported = absent for support purposes
    u6["MgSi"] = u6.Mg / u6.Si.where(u6.Si > 0)
    return u6


def rows_for(temper: str | None, series: str = "6xxx") -> pd.DataFrame:
    d = data(series)
    if temper and (d.temper == temper).sum() >= MIN_ROWS_PER_TEMPER:
        return d[d.temper == temper]
    return d


@lru_cache(maxsize=64)
def ranges(temper: str | None, series: str = "6xxx") -> dict:
    d = rows_for(temper, series)
    out = {"basis": f"{len(d)} measured {series} rows" + (f" ({temper})" if temper and len(d) < len(data(series)) else " (all tempers)"),
           "solutes": {}, "process": {}}
    for e in solutes(series) + (["MgSi"] if series == "6xxx" else []):
        v = d[e].dropna()
        v = v[v > 0] if e != "MgSi" else v
        if len(v) >= 5:
            out["solutes"][e] = [round(float(np.percentile(v, 5)), 3), round(float(np.percentile(v, 95)), 3)]
    for p in PROCESS:
        v = d[p].dropna()
        if len(v) >= 5:
            out["process"][p] = [round(float(np.percentile(v, 5)), 2), round(float(np.percentile(v, 95)), 2)]
    return out


@lru_cache(maxsize=8)
def _space(series: str = "6xxx"):
    """Standardized solute space over unique measured compositions of the series."""
    d = data(series).drop_duplicates("comp_key")
    x = d[solutes(series)].to_numpy(float)
    mu, sd = x.mean(0), x.std(0)
    sd[sd == 0] = 1.0
    z = (x - mu) / sd
    dist, _ = cKDTree(z).query(z, k=2)  # k=2: nearest measured composition other than itself
    thr = float(np.percentile(dist[:, 1], 95))
    return mu, sd, cKDTree(z), d.reset_index(drop=True), round(thr, 3)


def threshold(series: str = "6xxx") -> float:
    return _space(series)[4]


def nearest(comp: dict, temper: str | None = None, series: str = "6xxx") -> dict:
    """Closest measured composition of the series and its median measured strength."""
    mu, scale, tree, d, thr = _space(series)
    z = (np.array([comp.get(e, 0.0) for e in solutes(series)]) - mu) / scale
    dist, i = tree.query(z)
    key = d.loc[i, "comp_key"]
    same = data(series)[data(series).comp_key == key]
    if (~same.source.isin(sd.NOMINAL_SOURCES)).any():
        same = same[~same.source.isin(sd.NOMINAL_SOURCES)]
    if temper and (same.temper == temper).any():
        same = same[same.temper == temper]
    return {"distance": round(float(dist), 3),
            "composition": {e: round(float(d.loc[i, e]), 3) for e in solutes(series) if d.loc[i, e] > 0},
            "tempers": sorted(same.temper.dropna().unique().tolist()),
            "measured_median": {t: (None if same[t].isna().all() else round(float(same[t].median()), 1))
                                for t in ("UTS", "YTS", "EL")},
            "value_class": "nominal" if same.source.isin(sd.NOMINAL_SOURCES).all() else "measured",
            "n_measurements": int(len(same))}


def flags(cand: dict, series: str = "6xxx") -> list[str]:
    """Reasons the candidate is outside measured support of the series (empty list = inside)."""
    comp = cand["composition"]
    exact = data(series)
    for key, value in (("temper", cand.get("temper")), ("route", cand.get("route"))):
        if value is not None:
            exact = exact[exact[key] == value]
    for key in solutes(series) + list(PROCESS):
        value = comp.get(key, 0.0) if key in comp or key in solutes(series) else cand.get("process", {}).get(key)
        exact = exact[exact[key].isna()] if value is None else exact[np.isclose(exact[key].fillna(0.0), value)]
    if not exact.empty:
        return []
    r = ranges(cand.get("temper"), series)
    out = []
    for e, (lo, hi) in r["solutes"].items():
        if e == "MgSi":
            if comp.get("Si", 0) > 0:
                v = comp.get("Mg", 0) / comp["Si"]
                if not lo <= v <= hi:
                    out.append(f"Mg:Si {v:.2f} outside measured {lo}-{hi}")
            continue
        v = comp.get(e, 0.0)
        if v > hi:
            out.append(f"{e} {v:g} above measured {hi}")
        elif e in MAJOR[series] and v < lo:
            out.append(f"{e} {v:g} below measured {lo}")
    for p, (lo, hi) in r["process"].items():
        v = (cand.get("process") or {}).get(p)
        if v is not None and not lo <= v <= hi:
            out.append(f"process {p}={v:g} outside measured {lo}-{hi}")
    n = nearest(comp, cand.get("temper"), series)
    if n["distance"] > threshold(series):
        out.append(f"far from measured {series} alloys (distance {n['distance']} > {threshold(series)})")
    return out
