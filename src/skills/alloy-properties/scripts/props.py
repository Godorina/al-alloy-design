"""Import-only: the property terms the alloy-strength engine does not have.

Density from composition, the evidence-backed corrosion composition rules, and the
multi-property spec with its strength view (the spec the unchanged engine scores).
Script names in this folder must not repeat the engine's module names (step0_*, step1_examples,
step2_icl_predict, step3_corrosion, core): this folder is first on sys.path, so a clash would make
the engine import our file instead of its own.
"""
from __future__ import annotations

import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2] / "alloy-strength"
for _p in (ENGINE / "scripts", ENGINE / "icl"):
    if str(_p) not in sys.path:
        sys.path.insert(1, str(_p))

from step0_checks import STRENGTH, check_spec  # noqa: E402

# Pure-element densities, g/cm3 (CRC handbook, room temperature).
RHO = {"Al": 2.699, "Mg": 1.738, "Si": 2.33, "Cu": 8.96, "Zn": 7.14, "Mn": 7.21, "Fe": 7.87,
       "Cr": 7.19, "Ti": 4.51, "Zr": 6.52, "V": 6.11, "Ni": 8.91, "Sc": 2.99, "Sr": 2.64,
       "Sn": 7.29, "Co": 8.90, "Ag": 10.49, "Li": 0.737}
# Li is an effective in-alloy value, not pure Li (0.534): fitted on handbook 2195/2090/8090 densities,
# held-out 2099/2050/2196 agree within 0.4 %. Non-Li alloys (6061, 6082, 7075, 2024, 5083, A356) agree within 0.6 %.
DENSITY_NOTE = "computed from composition (specific-volume mixing, effective Li), about ±0.6 % vs handbook values"
REF_DENSITY = 2.70  # only to turn a specific_UTS target into a UTS target for example selection

# Corrosion composition rules, from the al6xxx KG v0.5.0 (checked 2026-10-01). These screen a
# composition; they do not predict a corrosion value.
MG2SI_RATIO = 1.73  # Mg:Si mass ratio of Mg2Si
CU_LIMIT = 0.2  # wt%. Measured IGC depth: 187-229 um for Cu 0.30-0.79 vs 32-152 um Cu-free (20 values)
EXCESS_SI_LIMIT = 0.15  # wt%. JSM rating medians: Excellent -0.03, Good +0.16 (275 nominal values)
RULE_SERIES = {"6xxx"}

PROPS = STRENGTH | {"specific_UTS"}
EXTRA_CONSTRAINTS = {"density_max"}


def density(comp: dict) -> float:
    """g/cm3 of an alloy given solute wt% (Al is the balance)."""
    w = {e: float(v) for e, v in comp.items() if e != "Al" and v}
    w["Al"] = 100.0 - sum(w.values())
    return round(100.0 / sum(v / RHO[e] for e, v in w.items()), 3)


def excess_si(comp: dict) -> float:
    """Si beyond Mg2Si stoichiometry and the Si held by Fe/Mn intermetallics (rule of thumb (Fe+Mn)/3), wt%."""
    g = comp.get
    return round(g("Si", 0.0) - g("Mg", 0.0) / MG2SI_RATIO - (g("Fe", 0.0) + g("Mn", 0.0)) / 3, 3)


def corrosion_rules(comp: dict, series: str) -> dict:
    """{covered, rules: [{rule, value, limit, ok, why}]}; covered=False where no rule has KG evidence yet."""
    if series not in RULE_SERIES:
        return {"covered": False, "rules": [],
                "note": f"no evidence-backed corrosion rule for {series} yet; judge by the KG evidence only"}
    cu, xs = round(comp.get("Cu", 0.0), 3), excess_si(comp)
    return {"covered": True, "rules": [
        {"rule": "Cu", "value": cu, "limit": CU_LIMIT, "ok": cu <= CU_LIMIT,
         "why": "Cu raises intergranular corrosion depth in the KG measurements"},
        {"rule": "excess_Si", "value": xs, "limit": EXCESS_SI_LIMIT, "ok": xs <= EXCESS_SI_LIMIT,
         "why": "excess Si is higher in JSM 'Good' than 'Excellent' alloys"}]}


def wants_corrosion(spec: dict) -> bool:
    return spec.get("corrosion") is True


def strength_view(spec: dict) -> dict:
    """The spec the alloy-strength engine understands: specific_UTS becomes a UTS objective
    (target x REF_DENSITY), density_max and corrosion are removed (this skill judges them)."""
    sv = {k: v for k, v in spec.items() if k != "corrosion"}
    if isinstance(spec.get("constraints"), dict):
        sv["constraints"] = {k: v for k, v in spec["constraints"].items() if k not in EXTRA_CONSTRAINTS}
    objs = []
    for o in spec.get("objectives") or []:
        if isinstance(o, dict) and o.get("property") == "specific_UTS":
            t = o.get("target")
            o = {"property": "UTS", "direction": o.get("direction", "maximize"),
                 **({"target": round(t * REF_DENSITY, 1)} if isinstance(t, (int, float)) else {})}
        objs.append(o)
    if "objectives" in spec:
        sv["objectives"] = objs
    return sv


def check_props(spec: dict) -> list[str]:
    """Problems of the multi-property spec; empty list = usable."""
    errs = []
    if "corrosion" in spec and not isinstance(spec["corrosion"], bool):
        errs.append("corrosion must be true or false")
    cons = spec.get("constraints")
    if isinstance(cons, dict) and "density_max" in cons:
        v = cons["density_max"]
        if not (isinstance(v, (int, float)) and 2.0 <= v <= 3.2):
            errs.append("density_max must be a number in g/cm3 between 2.0 and 3.2")
    for o in spec.get("objectives") or []:
        if isinstance(o, dict) and o.get("property") == "specific_UTS":
            if o.get("direction", "maximize") != "maximize":
                errs.append("specific_UTS can only be maximized")
            if not (isinstance(o.get("target"), (int, float)) and o["target"] > 0):
                errs.append("specific_UTS objectives need a positive target in MPa/(g/cm3), e.g. 140")
    errs += [e.replace("UTS_min/YTS_min/EL_min", "UTS_min/YTS_min/EL_min/density_max")
             for e in check_spec(strength_view(spec), STRENGTH)]
    return errs


def first_objective(spec: dict) -> tuple[str, int]:
    """(property, sign): the property the ranking uses and +1 to maximize / -1 to minimize."""
    o = next((o for o in spec.get("objectives") or [] if isinstance(o, dict) and o.get("property") in PROPS), {})
    return o.get("property", "UTS"), (-1 if o.get("direction") == "minimize" else 1)
