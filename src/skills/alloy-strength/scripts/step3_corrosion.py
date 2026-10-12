"""Corrosion evidence for strength candidates, from the al6xxx knowledge graph (ontology/al_alloy/al6xxx/build/kg.ttl).

For each candidate: references to the K samples of the spec series nearest in composition (Euclidean wt%
distance) that have a corrosion result. The response stores each sample and test string once under `samples`
and `tests`; values refer to their test by index. These are measured neighbours, NOT predictions: judge a
candidate by the alloys around it, and compare values only within one test (an Ecorr in 3.5% NaCl is not a
JSM rating).

Usage:
  step3_corrosion.py --spec '<spec JSON>' --candidates '<JSON list>' [--k 5]
"""
import argparse
import json
import os
from pathlib import Path

import pyoxigraph as ox

from step0_checks import SERIES, emit, fail, load_spec, normalize_candidate

ROOT = Path(__file__).resolve().parents[4]  # icl project (src/skills/<skill>/scripts/x.py)
KG = Path(os.environ.get("AL_ONTO", ROOT / "ontology" / "al_alloy" / "al6xxx")) / "build" / "kg.ttl"
AL = "https://w3id.org/al6xxx#"
NEAR_WT = 1.0  # a neighbour farther than this (wt%) says little about the candidate
KINDS = ["CorrosionPotential", "PittingPotential", "CorrosionCurrentDensity", "PolarizationResistance", "CorrosionRate",
         "CorrosionDepth", "SCCSusceptibility", "CorrosionRating"]
UNITS = {"V": "V", "MilliV": "mV", "GM-PER-M2-HR": "g/(m2 h)", "MilliM-PER-YR": "mm/y", "MicroM": "um", "PERCENT": "%",
         "A-PER-CentiM2": "A/cm2", "OHM-CentiM2": "ohm cm2"}
PREFIX = (f"PREFIX al: <{AL}> PREFIX qudt: <http://qudt.org/schema/qudt/> PREFIX prov: <http://www.w3.org/ns/prov#> "
          "PREFIX schema: <https://schema.org/> PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> "
          "PREFIX skos: <http://www.w3.org/2004/02/skos/core#> ")


def val(t):
    return None if t is None else t.value


def inferred_state(label: str, steps: set[str]) -> tuple[str, str] | None:
    """Known process/label evidence for a temper when the KG record has none."""
    label = label.casefold()
    if {"SolutionTreatment", "ArtificialAgeing"} <= steps:
        if "peak" in label:
            return "T6", "SolutionTreatment + ArtificialAgeing; label peak aged"
        if "over" in label:
            return "T7", "SolutionTreatment + ArtificialAgeing; label over aged"
    if steps == {"SolutionTreatment", "NaturalAgeing"}:
        return "T4", "SolutionTreatment + NaturalAgeing"
    if not steps and "as-cast" in label:
        return "F", "label as-cast; no process steps"
    return None


def state_match(sample: dict, temper: str | None) -> tuple[str | None, str | None]:
    if sample.get("temper") == temper:
        return "temper", None
    if not sample.get("temper"):
        inferred = inferred_state(sample["label"], sample.get("steps", set()))
        if inferred and inferred[0] == temper:
            return "inferred", inferred[1]
    return None, None


def corroded(series: str) -> dict:
    """sample IRI -> {label, temper, source, flags, composition, values} for samples of `series` with a corrosion result."""
    st = ox.Store()
    st.load(path=str(KG), format=ox.RdfFormat.TURTLE)
    sel = f'?ser skos:inScheme al:SeriesScheme ; skos:notation "{series}" . ?s al:ofAlloy ?a . ?a al:inSeries ?ser .'
    out: dict = {}
    for r in st.query(PREFIX + f"""SELECT ?s ?label ?des ?temper ?kind ?class ?x ?unit ?rating ?test ?medium ?testClass ?id ?name WHERE {{
        {sel} ?s al:hasPropertyValue ?v . ?v al:propertyKind ?kind ; a ?class .
        VALUES ?kind {{ {' '.join('al:' + k for k in KINDS)} }} VALUES ?class {{ al:MeasuredValue al:NominalValue }}
        OPTIONAL {{ ?v qudt:numericValue ?x }} OPTIONAL {{ ?v qudt:unit ?unit }} OPTIONAL {{ ?v al:ratingValue ?rating }}
        OPTIONAL {{ ?v al:underTest ?t . ?t al:testMethod ?m ; al:testClass ?testClass . OPTIONAL {{ ?t al:environment ?e }}
                   OPTIONAL {{ ?t al:referenceElectrode ?ref }}  # one string per test: method in medium vs reference
                   BIND (COALESCE(?e, "") AS ?medium) BIND (CONCAT(?m, COALESCE(CONCAT(" in ", ?e), ""), COALESCE(CONCAT(" vs ", ?ref), "")) AS ?test) }} OPTIONAL {{ ?s rdfs:label ?label }}
        OPTIONAL {{ ?a al:designation ?des }} OPTIONAL {{ ?s al:hasTemper ?temper }}
        OPTIONAL {{ ?s prov:wasDerivedFrom ?d . OPTIONAL {{ ?d schema:identifier ?id }} OPTIONAL {{ ?d schema:name ?name }} }}
    }}"""):
        s = out.setdefault(r["s"].value, {"label": val(r["label"]) or val(r["des"]) or r["s"].value.rsplit("/", 1)[1],
                                          "temper": (val(r["temper"]) or "").rsplit("#", 1)[-1] or None,
                                          "source": val(r["id"]) or val(r["name"]), "values": []})
        v = {"kind": r["kind"].value.rsplit("#", 1)[1], "class": "measured" if r["class"].value.endswith("MeasuredValue") else "nominal",
             "test": {"text": val(r["test"]), "class": val(r["testClass"]).rsplit("#", 1)[-1]}, "_medium": val(r["medium"])}
        if r["x"] is not None:
            v.update(value=float(r["x"].value), unit=UNITS.get(r["unit"].value.rsplit("/", 1)[1].rsplit("#", 1)[-1]) if r["unit"] else None)
        else:
            v["rating"] = val(r["rating"])
        if v not in s["values"]:
            s["values"].append(v)
    for r in st.query(PREFIX + f"""SELECT ?s ?e ?w WHERE {{ {sel} ?a al:hasConstituent [ al:element ?e ; al:massPercent ?w ] }}"""):
        if r["s"].value in out:
            out[r["s"].value].setdefault("composition", {})[r["e"].value] = float(r["w"].value)
    for r in st.query(PREFIX + f"SELECT ?s ?type WHERE {{ {sel} ?s al:hasProcessStep [ al:stepType ?type ] }}"):
        if r["s"].value in out:
            out[r["s"].value].setdefault("steps", set()).add(r["type"].value.rsplit("#", 1)[-1])
    for r in st.query(PREFIX + f"SELECT ?s ?f WHERE {{ {sel} ?s al:qualityFlag ?f }}"):
        if r["s"].value in out:
            out[r["s"].value].setdefault("flags", []).append(r["f"].value)
    return out


def distance(a: dict, b: dict) -> float:
    # ponytail: plain wt% distance; scale per element if dilute additions (Zr, Cr) must weigh more
    return round(sum((a.get(e, 0.0) - b.get(e, 0.0)) ** 2 for e in set(a) | set(b)) ** 0.5, 3)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--k", type=int, default=5)
    a = ap.parse_args()
    spec = load_spec(a.spec)
    series = spec.get("series", "6xxx")
    if series not in SERIES:
        fail(f"series must be one of {SERIES}")
    try:
        cands = json.loads(a.candidates)
    except json.JSONDecodeError as e:
        fail(f"candidates is not valid JSON: {e}")
    pool = {k: v for k, v in corroded(series).items() if v.get("composition")}  # designation-only: no distance
    results, rejected, samples, tests = [], [], {}, []

    def sample(k, v):
        if k not in samples:
            values = []
            for value in v["values"]:
                value = dict(value)
                test = value.pop("test", None)
                value.pop("_medium", None)
                if test not in tests:
                    tests.append(test)
                value["test"] = tests.index(test)
                values.append(value)
            samples[k.rsplit("/", 1)[1]] = {key: v[key] for key in ("label", "temper", "source", "composition")}
            samples[k.rsplit("/", 1)[1]]["values"] = values
            if v.get("flags"):
                samples[k.rsplit("/", 1)[1]]["flags"] = v["flags"]
        return k.rsplit("/", 1)[1]

    for i, c in enumerate(cands if isinstance(cands, list) else []):
        cid = c.get("id", f"c{i + 1}") if isinstance(c, dict) else f"c{i + 1}"
        norm, err = normalize_candidate(c, spec)
        if err:
            rejected.append({"id": cid, "error": err})
            continue
        comp = norm["composition"]
        near = [(k, v, distance(comp, v["composition"]), *state_match(v, spec.get("temper"))) for k, v in pool.items()]
        near = sorted(near, key=lambda x: x[2])[:max(1, min(a.k, 10))]
        neighbors = []
        for k, v, d, match, basis in near:
            neighbor = {"sample": sample(k, v), "distance": d, "far": d > NEAR_WT,
                        "same_temper": match == "temper", "state_match": match}
            if basis:
                neighbor["state_basis"] = basis
            neighbors.append(neighbor)
        has_near = any(not x["far"] for x in neighbors)
        ok = any(not x["far"] and x["state_match"] for x in neighbors)
        results.append({"id": cid, "composition": comp, "judgeable": ok, "neighbors": neighbors,
                        **({} if ok else {"note": f"{NEAR_WT:g} wt% 안에 실측 없음" if not has_near else
                                          "같은 템퍼의 부식 결과 없음 (공정 상태 추정 포함)"})})
    emit({"series": series, "pool": len(pool), "samples": samples, "tests": tests, "results": results, "rejected": rejected,
          "note": "measured/nominal corrosion results of the nearest alloys in the KG, not predictions; "
                  "compare values only within one test"})


if __name__ == "__main__":
    main()
