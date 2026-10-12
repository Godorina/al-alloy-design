"""In-context examples: measured alloys of the spec series (default 6xxx) closest to a strength target.

Repeated measurements of the same (composition, temper, route, process) are merged
to their median (the data has ~8 MPa scatter within one condition). The goal property is
the first strength objective (UTS, YTS or EL; else UTS) with its target (or <P>_min); only
alloys where it was measured are used. Alloys of the requested route and all others are
ranked separately (reported heat treatment first, then closeness to the goal) and taken in
turn, so the route is not buried under process-bearing rows that never report a route.
At most 2 examples per composition (diversity).

Usage:
  step1_examples.py --spec '<spec JSON>' [--k 16]
"""
import argparse
from itertools import zip_longest

import numpy as np

from step0_domain import PROCESS, data, ranges, solutes, threshold
from step0_data import NOMINAL_SOURCES
from step0_checks import TEMPERS, check_spec, emit, fail, load_spec, STRENGTH


def goal(spec: dict) -> tuple[str, float | None]:
    """(property, value): the first strength objective, else UTS; value from its target or <P>_min."""
    o = next((o for o in spec.get("objectives", []) if isinstance(o, dict) and o.get("property") in STRENGTH), {})
    prop = o.get("property", "UTS")
    v = o.get("target") or (spec.get("constraints") or {}).get(f"{prop}_min")
    return prop, (float(v) if v else None)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--k", type=int, default=16)
    a = ap.parse_args()
    spec = load_spec(a.spec)
    problems = check_spec(spec, STRENGTH)
    if problems:
        fail("spec problems", problems=problems)
    emit(examples_for(spec, a.k))


def examples_for(spec: dict, k: int = 16) -> dict:
    """The examples document; deterministic, so step2 can resolve a candidate's parent id."""
    temper, route, series = spec.get("temper"), spec.get("route"), spec.get("series", "6xxx")
    prop, target = goal(spec)
    if temper not in TEMPERS:
        fail(f"temper must be one of {sorted(TEMPERS)}")
    k = max(1, min(k, 30))

    d = data(series)
    d = d[d.temper == temper]
    if d.empty:
        fail(f"no measured {series} rows for temper {temper}")
    keys = ["comp_key", "route"] + PROCESS
    g = (d.groupby(keys, dropna=False)
           .agg(**{e: (e, "first") for e in solutes(series)},
                UTS=("UTS", "median"), YTS=("YTS", "median"), EL=("EL", "median"),
                n=("UTS", "size"), source=("source", "first"))
           .reset_index())
    g = g[g[prop].notna()]
    if g.empty:
        fail(f"no measured {series} {temper} rows with {prop}; try another temper")
    g["has_process"] = g[PROCESS].notna().any(axis=1)
    g["gap"] = (g[prop] - target).abs() if target else 0.0
    same = g.route == route
    ranked = [x.sort_values(["has_process", "gap"], ascending=[False, True]).iterrows()
              for x in (g[same], g[~same])]
    picked, per_comp = [], {}
    for _, r in (t for pair in zip_longest(*ranked) for t in pair if t is not None):
        if per_comp.get(r.comp_key, 0) >= 2:
            continue
        per_comp[r.comp_key] = per_comp.get(r.comp_key, 0) + 1
        picked.append(r)
        if len(picked) >= k:
            break
    ex = []
    for i, r in enumerate(picked, 1):
        ex.append({"id": f"M{i}",
                   "composition": {e: round(float(r[e]), 3) for e in solutes(series) if r[e] > 0},
                   "temper": temper, "route": r.route,
                   "process": {p: round(float(r[p]), 2) for p in PROCESS if not np.isnan(r[p])},
                   "measured": {t: (None if np.isnan(r[t]) else round(float(r[t]), 1))
                                for t in ("UTS", "YTS", "EL")},
                   "n_measurements": int(r.n), "source": r.source,
                   "value_class": "nominal" if r.source in NOMINAL_SOURCES else "measured"})
    return {"note": "measured or nominal (value_class) alloys, not predictions",
          "series": series, "temper": temper, "route_requested": route, "goal": {"property": prop, "value": target},
          "route_coverage": f"{int((d.route == route).sum())} of {len(d)} {temper} rows have route={route}",
          "examples": ex,
          "support": {"ranges": ranges(temper, series), "distance_threshold": threshold(series)}}


if __name__ == "__main__":
    main()
