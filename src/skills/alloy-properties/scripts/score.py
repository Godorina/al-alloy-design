"""Score multi-property candidates. The only scoring script of this skill.

The strength part is the alloy-strength scorer, unchanged, run on the strength view of the spec:
diversity check against each parent, ICL UTS/YTS from measured examples + CatBoost hint, CatBoost EL
with its 80 % error range, support flags, nearest measured alloy, strength and <Element>_max
constraints. Added here: computed density and specific UTS (ICL UTS / density, ML if no ICL), the
corrosion composition rules (6xxx), density_max and corrosion-rule violations, and the ranking:
in support with no violation first, then the first objective (UTS, YTS or specific_UTS).

Usage:
  score.py --spec '<spec JSON>' --candidates '<JSON list>' [--draws 4] [--final]
"""
import argparse
import json

from props import DENSITY_NOTE, check_props, corrosion_rules, density, first_objective, strength_view, wants_corrosion
from step0_checks import emit, fail, load_spec
import step2_icl_predict as eng


def add_properties(spec: dict, results: list) -> list:
    """Density, specific UTS, corrosion rules and the extra violations; re-ranked."""
    series, cons = spec.get("series", "6xxx"), spec.get("constraints") or {}
    out = []
    for r in results:
        r = dict(r)
        rho = density(r["composition"])
        icl_uts = r["icl"].get("UTS")
        uts, src = (icl_uts, "ICL") if icl_uts is not None else (r["ml"].get("UTS"), "ML")
        rules = corrosion_rules(r["composition"], series)
        viol = list(r["violations"])
        if "density_max" in cons and rho > cons["density_max"]:
            viol.append(f"density {rho} > density_max {cons['density_max']} (computed)")
        if wants_corrosion(spec):
            viol += [f"{x['rule']} {x['value']} > {x['limit']} (corrosion rule)" for x in rules["rules"] if not x["ok"]]
        r.update(density=rho, corrosion_rules=rules, violations=viol,
                 specific_UTS=None if uts is None else {"value": round(uts / rho, 1), "from": src})
        out.append(r)
    prop, sign = first_objective(spec)

    def objective(r: dict) -> float:
        if prop == "specific_UTS":
            v = (r["specific_UTS"] or {}).get("value")
        else:
            v = r["icl"].get(prop) if r["icl"].get(prop) is not None else r["ml"].get(prop)
        return -sign * v if v is not None else float("inf")

    out.sort(key=lambda r: (not (r["in_support"] and not r["violations"]), objective(r)))
    return out


def run(spec: dict, cands: list, draws: int = 4, final: bool = False, ask_fn=eng.ask, hints=None) -> dict:
    sv = strength_view(spec)
    targets = eng.targets_of(sv)
    drops = [] if final else eng.diversity_drops(sv, cands)
    dropped = {i for i, _ in drops}
    kept = [c for i, c in enumerate(cands) if i not in dropped]
    done = eng.finish(sv, targets, eng.score(sv, kept, targets, draws, hints=hints, ask_fn=ask_fn))
    series = spec.get("series", "6xxx")
    return {"note": eng.NOTE + "; density and specific UTS are computed; corrosion rules screen the composition",
            "targets": targets, "objective": first_objective(spec)[0],
            "data": {t: eng.load_conditions(t, series)[0] for t in targets},
            "disagree_threshold": {t: eng.DISAGREE[t] for t in targets},
            "distance_threshold": eng.threshold(series), "density_note": DENSITY_NOTE,
            "dropped": [{"id": (cands[i].get("id") if isinstance(cands[i], dict) else None) or f"C{i + 1}",
                         "reason": reason} for i, reason in drops],
            "results": add_properties(spec, done["results"]), "rejected": done["rejected"]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--draws", type=int, default=4)
    ap.add_argument("--final", action="store_true", help="last scoring of the chosen set: no diversity check")
    a = ap.parse_args()
    spec = load_spec(a.spec)
    problems = check_props(spec)
    if problems:
        fail("spec problems", problems=problems)
    try:
        cands = json.loads(a.candidates)
    except json.JSONDecodeError as e:
        fail(f"--candidates is not valid JSON: {e}")
    cands = [cands] if isinstance(cands, dict) else cands
    if not isinstance(cands, list) or not 0 < len(cands) <= eng.MAX_CANDS:
        fail(f"give 1-{eng.MAX_CANDS} candidates per call")
    if not 1 <= a.draws <= 4:
        fail("--draws must be 1-4")
    objectives = [o.get("property") for o in spec["objectives"] if isinstance(o, dict)]
    if objectives and all(p == "EL" for p in objectives):
        fail(f"EL cannot be optimised: ML EL error ~{eng.el_q80(spec.get('series', '6xxx')):.0f} %p "
             "(80th pct); give a strength or specific_UTS objective and EL_min")
    emit(run(spec, cands, a.draws, a.final))


if __name__ == "__main__":
    main()
