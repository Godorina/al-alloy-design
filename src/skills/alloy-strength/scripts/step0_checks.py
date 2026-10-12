"""Import-only: checks and output contract for the strength scripts.

Spec loading/validation, candidate normalisation with specific rejection reasons,
and the single-JSON stdout contract.
"""
from __future__ import annotations

import json
import sys


ALLOWED = ["Mg", "Si", "Cu", "Fe", "Mn", "Cr", "Zn", "Ti", "Zr", "V", "Ni", "Sc", "Sr", "Sn", "Co"]
MAX_SOLUTE = 15.0  # total wt%; per-series overrides in MAX_TOTAL
EXTRA_ELEMENTS = {"2xxx": ["Ag", "Li"], "AlLi": ["Li", "Ag"]}  # allowed only in these series
MAX_TOTAL = {"7xxx": 20.0, "cast_AlSi": 30.0}  # measured maxima 18.1 / 25.1 wt%; others MAX_SOLUTE
MAX_ONE = {"cast_AlSi": 25.0}  # hypereutectic Si up to 22 wt%; others 15

STRENGTH = {"UTS", "YTS", "EL"}  # unbounded units: objectives need a target
TEMPERS = {"T4", "T5", "T6", "T7", "T8", "H", "F"}  # H = strain hardened (5xxx), F = as fabricated
SERIES = ["2xxx", "5xxx", "6xxx", "7xxx", "AlLi", "cast_AlSi"]  # alloy series with measured strength data
ROUTES = {"sheet", "extrusion", "plate", "rolled", "forged"}
HINT_BOUNDS = {"ss_temp": (450, 600), "ss_time_h": (0.05, 24),
               "age1_temp": (100, 260), "age1_time_h": (0.1, 200)}
CANDIDATE_META = {"id", "parent", "rationale", "note", "name", "temper", "route", "process", "series"}
PROCESS_KEYS = set(HINT_BOUNDS) | {"homog_temp", "homog_time_h", "age2_temp", "age2_time_h",
                                   "n_ss_stages", "n_age_stages", "quenched"}


def emit(obj) -> None:
    """The only stdout write of a script: one compact JSON document."""
    print(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))


def fail(msg: str, **extra) -> None:
    emit({"error": msg, **extra})
    sys.exit(2)


def load_spec(arg: str) -> dict:
    """Spec from inline JSON only: args come from the model, so no file is ever read."""
    try:
        spec = json.loads(arg.strip())
    except json.JSONDecodeError as e:
        fail(f"spec is not valid JSON: {e}")
    if not isinstance(spec, dict):
        fail("spec must be a JSON object")
    return spec


def check_spec(spec: dict, props: set[str] = STRENGTH) -> list[str]:
    """Problems that would make scoring wrong or crash; empty list = usable."""
    errs = []
    for key in ("constraints", "process_hint"):
        if key in spec and not isinstance(spec[key], dict):
            errs.append(f"{key} must be an object")
    if errs:
        return errs
    objs = spec.get("objectives")
    if not isinstance(objs, list) or not objs:
        errs.append("objectives must be a non-empty list")
        objs = []
    for o in objs:
        if not isinstance(o, dict) or o.get("property") not in props:
            errs.append(f"objective property must be one of {sorted(props)}: {o}")
            continue
        d = o.get("direction", "maximize")
        if d not in ("maximize", "minimize"):
            errs.append(f"direction must be maximize|minimize: {o}")
        if d == "minimize" and not o.get("target"):
            errs.append(f"minimize objectives need a numeric target: {o}")
        if "target" in o and not (isinstance(o["target"], (int, float)) and o["target"] > 0):
            errs.append(f"target must be a positive number: {o}")
        elif o["property"] in STRENGTH and not o.get("target"):
            errs.append(f"{o['property']} objectives need a numeric target (MPa or %), "
                        f"e.g. from measured examples; record it as an assumption: {o}")
    elements = ALLOWED + EXTRA_ELEMENTS.get(spec.get("series", "6xxx"), [])
    allowed_cons = {"UTS_min", "YTS_min", "EL_min"} | {f"{e}_max" for e in elements}
    for k, v in (spec.get("constraints") or {}).items():
        if k not in allowed_cons:
            errs.append(f"unknown constraint '{k}' (use UTS_min/YTS_min/EL_min or <Element>_max)")
        elif not isinstance(v, (int, float)):
            errs.append(f"constraint {k} must be a number")
    if spec.get("series", "6xxx") not in SERIES:
        errs.append(f"series must be one of {SERIES}")
    if spec.get("temper") not in TEMPERS:
        errs.append(f"temper must be one of {sorted(TEMPERS)}")
    if spec.get("route") not in ROUTES:
        errs.append(f"route must be one of {sorted(ROUTES)}")
    for k, v in (spec.get("process_hint") or {}).items():
        lo_ok, hi_ok = HINT_BOUNDS.get(k, (None, None))
        if lo_ok is None:
            errs.append(f"unknown process_hint key '{k}' (use {sorted(HINT_BOUNDS)})")
        elif not (isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v)
                  and lo_ok <= v[0] <= v[1] <= hi_ok):
            errs.append(f"process_hint {k} must be [lo, hi] within {lo_ok}-{hi_ok}")
    return errs


def normalize_candidate(cand, spec: dict | None) -> tuple[dict | None, str | None]:
    """Candidate -> {composition, temper, route, process, parent, rationale} or (None, reason).

    Accepts the canonical {"composition": {...}} form and the flat form where element
    symbols sit at the top level next to temper/route/process. Reasons name the exact
    problem so the model can fix it in one retry."""
    if not isinstance(cand, dict):
        return None, "candidate must be a JSON object"
    series = (spec or {}).get("series", "6xxx")
    allowed = ALLOWED + EXTRA_ELEMENTS.get(series, [])
    c = dict(cand)
    comp = c.get("composition")
    if comp is None:  # flat form: {"Mg": 0.9, "Si": 0.6, "temper": "T6"}
        # every non-meta key is treated as an element so typos are rejected, not dropped
        comp = {k: v for k, v in c.items() if k not in CANDIDATE_META}
        if not comp:
            return None, ('no composition: give {"composition": {"Mg": 0.9, "Si": 0.6, ...}} '
                          f"with elements from {allowed}")
    if not isinstance(comp, dict):
        return None, "composition must be an object of element: wt%"
    comp = {k: v for k, v in comp.items() if k != "Al"}  # Al is always the balance
    unknown = sorted(set(comp) - set(allowed))
    if unknown:
        return None, f"elements not allowed for {series}: {unknown} (allowed: {allowed})"
    try:
        vals = {k: float(v) for k, v in comp.items()}
    except (TypeError, ValueError):
        return None, "composition values must be numbers (wt%)"
    neg = [k for k, v in vals.items() if v < 0]
    if neg:
        return None, f"negative wt% for {neg}"
    vals = {k: v for k, v in vals.items() if v > 0}  # explicit 0 = element absent
    if not vals:
        return None, "composition has no solute above 0 wt%"
    one, total = MAX_ONE.get(series, 15.0), MAX_TOTAL.get(series, MAX_SOLUTE)
    big = [k for k, v in vals.items() if v > one]
    if big:
        return None, f"wt% above {one:g} for {big}"
    if sum(vals.values()) > total:
        return None, f"total solute {sum(vals.values()):.2f} wt% exceeds {total}"
    if spec:
        for k in ("temper", "route"):
            if not c.get(k):
                c[k] = spec.get(k)
    if c.get("temper") is not None and c["temper"] not in TEMPERS:
        return None, f"temper must be one of {sorted(TEMPERS)}"
    if c.get("route") is not None and str(c["route"]).lower() not in ROUTES:
        return None, f"route must be one of {sorted(ROUTES)}"
    proc = c.get("process")
    if proc is not None:
        if not isinstance(proc, dict):
            return None, "process must be an object"
        bad = [k for k, v in proc.items() if k not in PROCESS_KEYS
               or isinstance(v, bool) or not isinstance(v, (int, float))]
        if bad:
            return None, f"process keys must be numeric and one of {sorted(PROCESS_KEYS)}: {bad}"
    return {"composition": vals, "temper": c.get("temper"),
            "route": (c.get("route") or "").lower() or None,
            "process": proc or {}, "parent": c.get("parent"),
            "rationale": str(c.get("rationale", ""))[:160]}, None
