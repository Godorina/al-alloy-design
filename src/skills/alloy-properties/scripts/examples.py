"""In-context examples for a multi-property design. No LLM.

The alloy-strength selection (same rows and ids M1..M30 of the strength view of the spec, so a
candidate's parent resolves when scoring) is re-ordered: examples that meet every non-strength
requirement come first (measured EL >= EL_min, computed density <= density_max, the corrosion
composition rules when corrosion is requested), keeping the engine order inside each group.
Each example carries its density, measured specific UTS and corrosion-rule status.

Usage:
  examples.py --spec '<spec JSON>' [--k 16]
"""
import argparse

from props import DENSITY_NOTE, check_props, corrosion_rules, density, strength_view, wants_corrosion
from step0_checks import emit, fail, load_spec
from step1_examples import examples_for

POOL = 30  # the engine's largest example set; parents of candidates must come from it


def annotate(e: dict, spec: dict) -> dict:
    rho = density(e["composition"])
    uts = e["measured"].get("UTS")
    rules = corrosion_rules(e["composition"], spec.get("series", "6xxx"))
    cons = spec.get("constraints") or {}
    meets = {}
    if "EL_min" in cons:
        el = e["measured"].get("EL")
        meets["EL_min"] = None if el is None else el >= cons["EL_min"]
    if "density_max" in cons:
        meets["density_max"] = rho <= cons["density_max"]
    if wants_corrosion(spec) and rules["covered"]:
        meets["corrosion_rules"] = all(r["ok"] for r in rules["rules"])
    return dict(e, density=rho, specific_UTS=None if uts is None else round(uts / rho, 1),
                corrosion_rules=rules, meets=meets)


def examples_doc(spec: dict, k: int = 16) -> dict:
    doc = examples_for(strength_view(spec), POOL)
    ex = [annotate(e, spec) for e in doc["examples"]]
    meets_all = [all(v is True for v in e["meets"].values()) for e in ex]
    ordered = [e for e, ok in zip(ex, meets_all) if ok] + [e for e, ok in zip(ex, meets_all) if not ok]
    return dict(doc, examples=ordered[:max(1, min(k, POOL))], pool=len(ex), n_meeting_all=sum(meets_all),
                density_note=DENSITY_NOTE,
                note="measured or nominal (value_class) alloys, not predictions; examples meeting every "
                     "non-strength requirement (meets) come first")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--k", type=int, default=16)
    a = ap.parse_args()
    spec = load_spec(a.spec)
    problems = check_props(spec)
    if problems:
        fail("spec problems", problems=problems)
    emit(examples_doc(spec, a.k))


if __name__ == "__main__":
    main()
