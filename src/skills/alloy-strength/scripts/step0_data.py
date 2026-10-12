"""Import-only: unified strength data paths, column schema, and the ML feature row.

The column lists define the 64-column input of the saved CatBoost models
(skills/alloy-strength/icl/ml_model/spec.json); strength_row() turns a candidate into that row.
"""

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = (
    Path(__file__).resolve().parents[4]
)  # project root (src/skills/<skill>/scripts/x.py)
A = ROOT / "data" / "alloy-properties"
DATA = {
    "v1": A / "strength_unified" / "output",
    "v2": A / "strength_unified" / "output_v2",
    "v3": A / "strength_unified" / "output_v2",
}
LIT_ROWS = A / "lit_rows.parquet"

ELEMS30 = [
    "Ag",
    "B",
    "Be",
    "Bi",
    "Cd",
    "Ce",
    "Co",
    "Cr",
    "Cu",
    "Er",
    "Eu",
    "Fe",
    "Ga",
    "Hf",
    "Li",
    "Mg",
    "Mn",
    "Nd",
    "Ni",
    "Pb",
    "Sc",
    "Si",
    "Sn",
    "Sr",
    "Ti",
    "V",
    "Y",
    "Zn",
    "Zr",
    "Al",
]
PROC_COLS = [
    "corr_env",
    "homog_temp",
    "homog_time_h",
    "ss_temp",
    "ss_time_h",
    "n_ss_stages",
    "quenched",
    "age1_temp",
    "age1_time_h",
    "age2_temp",
    "age2_time_h",
    "n_age_stages",
    "has_ss",
    "has_ss_time",
    "has_age1",
    "has_age2",
    "has_l1",
    "n_elems_reported",
]
TEMPERS = ["F", "H", "T4", "T5", "T6", "T7", "T8", "W", "nan"]
ROUTES = ["extrusion", "forged", "plate", "rolled", "sheet", "unknown", "nan"]
NOMINAL_SOURCES = {"rec6"}
SOLUTES = ["Mg", "Si", "Cu", "Fe", "Mn", "Cr", "Zn", "Ti", "Zr"]
EXTRA_SOLUTES = {"2xxx": ["Ag", "Li"], "AlLi": ["Li", "Ag"]}
PROCESS = ["ss_temp", "ss_time_h", "age1_temp", "age1_time_h"]


def solutes(series: str = "6xxx") -> list[str]:
    return SOLUTES + EXTRA_SOLUTES.get(series, [])


@lru_cache(maxsize=3)
def table(version: str) -> pd.DataFrame:
    if version not in DATA:
        raise ValueError(f"data must be one of {sorted(DATA)}")
    u = pd.read_parquet(DATA[version] / "unified_strength.parquet")
    if version == "v3":
        if not LIT_ROWS.is_file():
            raise FileNotFoundError("run paper-extract/scripts/export_rows.py first")
        u = pd.concat([u, pd.read_parquet(LIT_ROWS)], ignore_index=True)
    return u


def unified() -> pd.DataFrame:
    """The v3 unified strength table used for support, examples, and nearest neighbours."""
    return table("v3")


def strength_row(cand):
    """Candidate {composition, temper, route, process} -> (feature row dict, composition with Al)."""
    comp = {e: float(cand["composition"].get(e, np.nan)) for e in ELEMS30[:-1]}
    comp["Al"] = 100.0 - sum(v for v in comp.values() if np.isfinite(v))
    p = dict.fromkeys(PROC_COLS, np.nan)
    p["corr_env"] = float(cand.get("corr_env", 0))
    proc = cand.get("process") or {}
    have_l1 = any(k in proc for k in ("ss_temp", "age1_temp", "homog_temp"))
    p["has_l1"] = float(have_l1)
    for k in (
        "homog_temp",
        "homog_time_h",
        "ss_temp",
        "ss_time_h",
        "age1_temp",
        "age1_time_h",
        "age2_temp",
        "age2_time_h",
    ):
        if k in proc:
            p[k] = float(proc[k])
    if have_l1:
        p["n_ss_stages"] = float(proc.get("n_ss_stages", 1 if "ss_temp" in proc else 0))
        p["n_age_stages"] = float(
            proc.get(
                "n_age_stages",
                (1 if "age1_temp" in proc else 0) + (1 if "age2_temp" in proc else 0),
            )
        )
        p["quenched"] = float(proc.get("quenched", 1))
        p["has_ss"], p["has_ss_time"] = (
            float("ss_temp" in proc),
            float("ss_time_h" in proc),
        )
        p["has_age1"], p["has_age2"] = (
            float("age1_temp" in proc),
            float("age2_temp" in proc),
        )
    p["n_elems_reported"] = float(
        sum(v != 0 for v in list(comp.values())[:-1] if np.isfinite(v))
    )
    raw = {**comp, **p}
    raw["temper"] = cand.get("temper", "nan") or "nan"
    raw["route"] = (cand.get("route") or "nan").lower()
    row = {c: raw.get(c, np.nan) for c in ELEMS30 + PROC_COLS}
    for t in TEMPERS:
        row[f"temper_{t}"] = float(raw["temper"] == t)
    for r in ROUTES:
        row[f"route_{r}"] = float(raw["route"] == r)
    return row, comp
