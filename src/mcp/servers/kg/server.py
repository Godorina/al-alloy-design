#!/usr/bin/env python3
"""kg/server.py -- the al6xxx knowledge graph (ontology/al_alloy/al6xxx/build/kg.ttl) as MCP tools.

Each tool is one competency question of ../ontology/al_alloy/al6xxx/docs/cq.md, run by ../ontology/al_alloy/common/check.cq on
an in-memory Oxigraph store loaded once. Values are tagged measured / nominal / predicted;
never present a nominal (JSM spec) value as a measurement.

Tools:
  find_samples(mg_min, mg_max, si_min, si_max, cu_max, limit)   # CQ1 composition window (wt%)
  strong_samples(temper, uts_min, el_min, limit)                 # CQ6 measured strength filter
  sample_detail(sample_id)                                       # CQ3/5/7/9 one sample in full
  sparql(query, limit)                                           # read-only SPARQL query, capped
  ml_studies(property, series, limit)                            # alml KG: ML studies predicting a property
  corrosion_values(kind, medium, series, limit)                  # CQ11 corrosion values + test, potentials vs SCE
Rebuild the KG after data changes: cd ../ontology/al_alloy/al6xxx && ../../../mlp-icl-llmsr/.venv/bin/python convert/build_kg.py
(alml: the same in ../ontology/al_alloy/alml)
"""
from __future__ import annotations

import json
import os
import re
import sys
from functools import lru_cache
from pathlib import Path

import pyoxigraph as ox
from mcp.server.fastmcp import FastMCP
from rdflib import URIRef

ROOT = Path(__file__).resolve().parents[4]  # project root (src/mcp/servers/kg/server.py)
ONTO = Path(os.environ.get("AL_ONTO", ROOT / "ontology" / "al_alloy" / "al6xxx"))
sys.path.insert(0, str(ONTO.parent / "common"))
from check import tools  # noqa: E402
from units import CORROSION  # noqa: E402  (corrosion property kinds, shared with the extraction checker)

_, cq = tools(ONTO)
ALML = ONTO.parent / "alml"  # ML studies of Al alloys (study-extract records)
_, ml_cq = tools(ALML)

KG = ONTO / "build" / "kg.ttl"
E, AL = "https://w3id.org/al6xxx/entity/", "https://w3id.org/al6xxx#"
ML, MLE = "https://w3id.org/alml#", "https://w3id.org/alml/entity/"
SHORT = {E: "", AL: "al:", "http://qudt.org/vocab/unit/": "unit:", ML: "", MLE: ""}
MAX_LIMIT = 100
mcp = FastMCP("kg")


@lru_cache(maxsize=1)
def store() -> ox.Store:
    st = ox.Store()
    st.load(path=str(KG), format=ox.RdfFormat.TURTLE)
    return st


@lru_cache(maxsize=1)
def ml_store() -> ox.Store:
    st = ox.Store()
    st.load(path=str(ALML / "build" / "kg.ttl"), format=ox.RdfFormat.TURTLE)
    return st


def short(t) -> str | None:
    if t is None:
        return None
    s = t.value if isinstance(t, (ox.NamedNode, ox.Literal)) else str(t)
    return next((p + s[len(ns):] for ns, p in SHORT.items() if s.startswith(ns)), s)


def page(rows: list[dict], limit) -> str:
    n = max(1, min(int(limit), MAX_LIMIT))
    return json.dumps({"total": len(rows), "rows": [{k: short(v) for k, v in r.items()} for r in rows[:n]]},
                      ensure_ascii=False)


def err(msg: str) -> str:
    return json.dumps({"error": msg}, ensure_ascii=False)


@mcp.tool()
async def find_samples(mg_min: float = 0.6, mg_max: float = 1.0, si_min: float = 0.4, si_max: float = 0.8,
                       cu_max: float = 0.1, limit: int = 30) -> str:
    """Samples whose alloy lies in a composition window (wt%), with temper and route (CQ1).
    An unreported Cu counts as 0. Returns {total, rows:[{sample, alloy, mg, si, cu, temper, route}]}."""
    try:
        b = {"mgMin": float(mg_min), "mgMax": float(mg_max), "siMin": float(si_min), "siMax": float(si_max),
             "cuMax": float(cu_max)}
        return page(cq(store(), "cq01", b), limit)
    except (TypeError, ValueError) as e:
        return err(f"numbers expected: {e}")


@mcp.tool()
async def strong_samples(temper: str = "T6", uts_min: float = 300, el_min: float = 10, series: str = "6xxx",
                         route: str = "", limit: int = 30) -> str:
    """Samples of one alloy series in a temper with MEASURED UTS >= uts_min (MPa) and EL >= el_min (%), strongest
    first (CQ6). series: 2xxx 5xxx 6xxx 7xxx AlLi cast_AlSi. temper: T4 T5 T6 T7 T8 F W H.
    route (optional): extrusion sheet plate rolled forged wire drawn cast printed - only samples whose source states it
    (most table data has no route). Returns {total, rows:[{sample, alloy, uts, el}]}; use sample_detail next."""
    if not re.fullmatch(r"T[4-8]|F|W|H", str(temper)):
        return err("temper must be one of T4 T5 T6 T7 T8 F W H")
    series_iri = next((URIRef(c.value) for c, n in store().query(
        f"PREFIX skos: <http://www.w3.org/2004/02/skos/core#> SELECT ?c ?n WHERE {{ ?c skos:inScheme <{AL}SeriesScheme> ; "
        "skos:notation ?n }") if n.value == str(series)), None)
    if series_iri is None:
        return err("series must be one of 2xxx 5xxx 6xxx 7xxx AlLi cast_AlSi")
    routes = {c.value.rsplit("#", 1)[1].lower(): c.value for (c,) in store().query(
        f"PREFIX skos: <http://www.w3.org/2004/02/skos/core#> SELECT ?c WHERE {{ ?c skos:inScheme <{AL}RouteScheme> }}")}
    if route and str(route).lower() not in routes:
        return err(f"route must be one of {' '.join(sorted(routes))}")
    try:
        rows = cq(store(), "cq06", {"temper": URIRef(AL + temper), "utsMin": float(uts_min),
                                    "elMin": float(el_min), "series": series_iri})
    except (TypeError, ValueError) as e:
        return err(f"numbers expected: {e}")
    if route:  # ponytail: filtered after the query; a cq06 route parameter when this is slow
        stated = {s.value for (s,) in store().query(
            f"PREFIX al: <{AL}> SELECT ?s WHERE {{ ?s al:hasRoute <{routes[str(route).lower()]}> }}")}
        rows = [r for r in rows if str(getattr(r["sample"], "value", r["sample"])) in stated]
    try:
        return page(rows, limit)
    except (TypeError, ValueError) as e:
        return err(f"numbers expected: {e}")


@mcp.tool()
async def sample_detail(sample_id: str) -> str:
    """Everything about one sample (e.g. "sample-ji-35"): alloy composition, process steps in order (CQ3),
    steps its temper requires but the source does not report (CQ5), quality flags (doubtful values), every value with its class
    measured/nominal/predicted (CQ7) and, for extracted papers, page + quote evidence (CQ9)."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", str(sample_id)):
        return err("sample_id looks like sample-<source>-<row>, e.g. sample-ji-35")
    s = URIRef(E + sample_id)
    alloy = [r["a"] for r in store().query(f"PREFIX al: <{AL}> SELECT ?a WHERE {{ <{s}> al:ofAlloy ?a }}")]
    if not alloy:
        return err(f"no sample {sample_id}")
    comp = list(store().query(  # empty when the paper gives only a standard designation
        f"PREFIX al: <{AL}> SELECT ?element ?wt WHERE {{ <{alloy[0].value}> al:hasConstituent "
        f"[ al:element ?element ; al:massPercent ?wt ] }} ORDER BY ?element"))
    names = sorted(r["d"].value for r in store().query(f"PREFIX al: <{AL}> SELECT ?d WHERE {{ <{alloy[0].value}> al:designation ?d }}"))
    one = {"sample": s}
    flags = sorted(r["f"].value for r in store().query(f"PREFIX al: <{AL}> SELECT ?f WHERE {{ <{s}> al:qualityFlag ?f }}"))
    label = [r["l"].value for r in store().query(f"SELECT ?l WHERE {{ <{s}> <http://www.w3.org/2000/01/rdf-schema#label> ?l }}")]
    return json.dumps({
        "sample": sample_id, "label": label[0] if label else None, "alloy": short(alloy[0]), "designation": names,
        "composition_wt": {r["element"].value: float(r["wt"].value) for r in comp},
        "flags": flags,  # doubtful values: say so when using this sample
        "steps": [{k: short(v) for k, v in r.items() if k != "sample"} for r in cq(store(), "cq03", one)],
        "missing_steps": [short(r["missing"]) for r in cq(store(), "cq05", one)],
        "values": [{k: float(v) if k == "numericValue" else short(v) for k, v in r.items()
                    if k not in ("sample", "value") and v is not None} for r in cq(store(), "cq07", one)],
        "evidence": [{k: short(v) for k, v in r.items() if k not in ("sample", "value")} for r in cq(store(), "cq09", one)],
    }, ensure_ascii=False)


PREFIXES = {"al": str(AL), "e": str(E), "qudt": "http://qudt.org/schema/qudt/",
            "skos": "http://www.w3.org/2004/02/skos/core#", "rdfs": "http://www.w3.org/2000/01/rdf-schema#"}


@mcp.tool()
async def sparql(query: str, limit: int = 30) -> str:
    """Read-only SPARQL SELECT/ASK over the KG (prefixes: al: <https://w3id.org/al6xxx#>,
    qudt: <http://qudt.org/schema/qudt/>, entities <https://w3id.org/al6xxx/entity/>). Prefer the fixed tools; use
    this for questions they miss. Returns {total, rows} (SELECT) or {answer} (ASK). PREFIX lines for al: e: qudt:
    skos: rdfs: are added when missing.
    Schema (use only these):
      ?sample al:ofAlloy ?alloy ; al:hasTemper al:T6 ; al:hasRoute al:Extrusion ; al:qualityFlag "reason" .
      ?alloy al:inSeries al:Series6xxx ; al:designation "6061" ; al:hasConstituent [ al:element "Mg" ; al:massPercent 0.9 ] .
      ?sample al:hasProcessStep ?step . ?step al:stepIndex 1 ; al:stepType al:SolutionTreatment ;
        al:temperatureC 540 ; al:durationH 0.5 ; al:heatingMethod al:Infrared .
      ?sample al:hasPropertyValue ?v . ?v a al:MeasuredValue ; al:propertyKind al:UTS ; qudt:numericValue 300 ;
        qudt:unit ?unit ; al:underTest ?test . ?test al:testMethod "potentiodynamic polarization" ;
        al:environment "3.5 wt% NaCl, 25 °C" ; al:referenceElectrode "SCE" .   (a sample can have several tests)
      ?sample rdfs:label "7001, as-cast" .   (the paper's name; extracted papers only)
    For "highest/lowest/top N" questions put ORDER BY DESC(?x) / ORDER BY ?x and LIMIT N in the query itself -
    do not sort returned rows yourself.
    Values: temper al:T4 al:T6 ...; route al:Extrusion al:Sheet al:Forged ...; step al:Homogenization al:Quenching
    al:ArtificialAgeing al:NaturalAgeing al:HotRolling al:ColdRolling al:ColdWorking al:Annealing; kind al:UTS al:YTS al:EL al:CorrosionPotential al:PittingPotential (V or mV vs the
    test's reference electrode: compare only on one reference) al:CorrosionCurrentDensity (A/cm2) al:PolarizationResistance
    (ohm cm2) al:CorrosionRate al:CorrosionDepth al:SCCSusceptibility al:CorrosionRating (al:ratingValue)
    al:ElectricalConductivity (MS/m);
    value class al:MeasuredValue al:NominalValue al:PredictedValue."""
    q = str(query)
    q = "\n".join([f"PREFIX {p}: <{iri}>" for p, iri in PREFIXES.items()
                   if not re.search(rf"(?i)\bPREFIX\s+{p}:", q)] + [q])  # the model often leaves them out
    try:
        res = store().query(q)  # Store.query parses queries only; updates are a syntax error
    except (SyntaxError, ValueError, OSError) as e:
        return err(f"not a valid read-only query: {e}")
    if isinstance(res, bool):
        return json.dumps({"answer": res})
    if not isinstance(res, ox.QuerySolutions):
        return err("only SELECT and ASK are supported")
    names = [v.value for v in res.variables]
    return page([{n: row[n] for n in names} for row in res], limit)


@mcp.tool()
async def ml_studies(property: str = "UTS", series: str = "", limit: int = 10) -> str:
    """Machine-learning studies of Al alloys that predict a property (alml KG, CQ1/3/4): per study the title, DOI,
    task type, alloy series, datasets (size, source), the best scores per model and metric (R2/accuracy-like higher
    is better, errors lower), whether the predictions were checked on newly made alloys (validated), and review
    status - "unreviewed" means no human has checked the record yet; say so when you use it.
    property: UTS YTS EL Hardness CorrosionRate CorrosionPotential PittingPotential FatigueLife ThermalConductivity ...
    series (optional): 1xxx 2xxx 3xxx 4xxx 5xxx 6xxx 7xxx AlLi cast_AlSi cast_AlMg."""
    q = ("PREFIX skos: <http://www.w3.org/2004/02/skos/core#> SELECT ?c WHERE {{ ?c skos:inScheme <{}> }}")
    kinds = {c.value.rsplit("#", 1)[1] for (c,) in ml_store().query(q.format(AL + "PropertyKindScheme"))}
    if property not in kinds:
        return err(f"property must be one of {' '.join(sorted(kinds))}")
    if series and series not in {n.value for (n,) in ml_store().query(
            f"PREFIX skos: <http://www.w3.org/2004/02/skos/core#> SELECT ?n WHERE {{ ?c skos:inScheme <{AL}SeriesScheme> ; skos:notation ?n }}")}:
        return err("series must be one of 1xxx 2xxx 3xxx 4xxx 5xxx 6xxx 7xxx AlLi cast_AlSi cast_AlMg")
    prop = {"property": URIRef(AL + property)}
    meta = {r["s"].value: r for r in ml_store().query(
        f"PREFIX ml: <{ML}> PREFIX schema: <https://schema.org/> SELECT ?s ?doi ?status ?validated WHERE {{ "
        "?s a ml:Study ; schema:identifier ?doi ; ml:reviewStatus ?status ; ml:experimentallyValidated ?validated }")}
    rows = {}
    for r in ml_cq(ml_store(), "cq01", prop):
        st = str(r["study"])
        if series and series not in str(r["series"] or "").split():
            continue
        m = meta[st]
        rows.setdefault(st, {"study": short(r["study"]), "title": str(r["title"]), "doi": m["doi"].value,
                             "task_type": [], "series": str(r["series"] or "").split(), "datasets": [], "scores": [],
                             "validated": m["validated"].value == "true", "status": m["status"].value})
        rows[st]["task_type"].append(short(r["taskType"]))
    for r in ml_cq(ml_store(), "cq04", prop):
        if str(r["study"]) in rows:
            rows[str(r["study"])]["datasets"].append({"size": short(r["size"]), "source": short(r["source"])})
    for r in ml_cq(ml_store(), "cq03", prop):  # best first per metric; keep one per model and metric
        sc = rows.get(str(r["study"]), {}).get("scores")
        key = {"algorithm": short(r["algorithm"]), "metric": short(r["metric"])}
        if sc is not None and len(sc) < 6 and not any(s["algorithm"] == key["algorithm"] and s["metric"] == key["metric"] for s in sc):
            sc.append({**key, "value": float(r["value"].value if hasattr(r["value"], "value") else r["value"]),
                       "split": short(r["split"])})
    out = list(rows.values())  # already plain values; page() would stringify the lists
    return json.dumps({"total": len(out), "rows": out[:max(1, min(int(limit), MAX_LIMIT))]}, ensure_ascii=False)


@mcp.tool()
async def corrosion_values(kind: str = "CorrosionPotential", medium: str = "", series: str = "", limit: int = 30) -> str:
    """MEASURED corrosion values of one kind with the test that produced them (CQ11), to compare alloys.
    kind: CorrosionPotential PittingPotential CorrosionCurrentDensity PolarizationResistance CorrosionRate
    CorrosionDepth SCCSusceptibility. medium (optional): text the test medium must contain, e.g. "3.5% NaCl".
    series (optional): 2xxx 5xxx 6xxx 7xxx AlLi cast_AlSi. Potentials also come as vsSCE (V vs SCE, converted from
    Ag/AgCl or SHE; empty for another reference electrode). Rows are ordered by method, medium, then value: compare
    values only within one method and medium. Returns {total, rows:[{sample, label, series, value, unit, vsSCE,
    method, medium, reference, source}]}; use sample_detail for composition and process."""
    if kind not in CORROSION:
        return err(f"kind must be one of {' '.join(CORROSION)}")
    rows = cq(store(), "cq11", {"kind": URIRef(AL + kind)})
    if series:
        notation = {c.value: n.value for c, n in store().query(
            f"PREFIX skos: <http://www.w3.org/2004/02/skos/core#> SELECT ?c ?n WHERE {{ ?c skos:inScheme <{AL}SeriesScheme> ; "
            "skos:notation ?n }")}
        if series not in notation.values():
            return err(f"series must be one of {' '.join(sorted(notation.values()))}")
        rows = [r for r in rows if notation.get(str(r["series"])) == series]
    squash = lambda t: re.sub(r"\s+", "", str(t or "")).lower()  # noqa: E731  ("3.5 wt% NaCl" ~ "3.5wt%nacl")
    rows = [r for r in rows if squash(medium) in squash(r["medium"])]
    try:
        return page(rows, limit)
    except (TypeError, ValueError) as e:
        return err(f"numbers expected: {e}")


if __name__ == "__main__":
    mcp.run()  # stdio transport
