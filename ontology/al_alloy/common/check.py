"""Check an ontology folder's data: parse schema + files, OWL-RL reasoning (owlrl), SHACL (pyshacl),
cross-value rules and CQ row counts (Oxigraph).

Usage: ../icl/.venv/bin/python common/check.py <ontology dir> [DATA.ttl ...]   -> one JSON document
In code:  check, cq = tools(ONTO_DIR)

Folder convention (every ontology under ontology/ follows it):
  schema/*.ttl   classes, properties, alignments (all loaded, with the shared common/*.ttl vocabularies)
  shapes/*.ttl   SHACL shapes;  shapes/*.rq  rules SHACL-core cannot express, each row = one
                 violation with ?focus ?message (pyshacl runs SPARQL constraints on rdflib and
                 took >6 min on 3e4 triples, so rules run in Oxigraph instead)
  cq/cq*.rq      competency questions; a header line `# params: name=value ...` gives defaults
                 (numbers, or prefix:Term resolved with the query's own PREFIX lines)
cq() binds parameters with a VALUES block at the top of the WHERE clause and runs the query in
Oxigraph (rdflib's SPARQL engine reorders joins statically and took >10 min on a 3e4-triple graph).
"""
import json
import re
import sys
from functools import partial
from pathlib import Path

import owlrl
import pyoxigraph as ox
from pyshacl import validate
from rdflib import Graph, Literal, Namespace, URIRef

OWLRL_ERROR = URIRef("http://www.daml.org/2002/03/agents/agent-ont#error")  # where owlrl records inconsistencies
SH = Namespace("http://www.w3.org/ns/shacl#")


def schema_files(onto: Path) -> list[Path]:
    """The ontology's own schema/*.ttl plus the shared vocabularies in ontology/common/*.ttl."""
    return [*sorted((onto / "schema").glob("*.ttl")), *sorted((Path(__file__).parent).glob("*.ttl"))]


def load(onto: Path, files, extra: str | None = None) -> Graph:
    g = Graph()
    for f in [*schema_files(onto), *files]:
        g.parse(f)
    if extra:
        g.parse(data=extra, format="turtle")
    return g


def params(text: str) -> dict:
    prefixes = dict(re.findall(r"^PREFIX\s+(\w*):\s*<([^>]+)>", text, re.M))
    m = re.search(r"^# params: (.*)$", text, re.M)
    out = {}
    for kv in (m.group(1).split() if m else []):
        k, v = kv.split("=")
        pfx, _, local = v.partition(":")
        out[k] = URIRef(prefixes[pfx] + local) if local and pfx in prefixes else Literal(float(v))
    return out


def sparql_term(v) -> str:
    """Only numbers and IRIs may be bound: this is where caller values enter the query text."""
    if isinstance(v, URIRef):
        if not re.fullmatch(r"https?://[^\s<>\"{}|\\^`]+", str(v)):
            raise ValueError(f"bad IRI: {v!r}")
        return f"<{v}>"
    return repr(float(v.toPython() if isinstance(v, Literal) else v))


def to_rdflib(t):
    if t is None or isinstance(t, ox.NamedNode):
        return None if t is None else URIRef(t.value)
    return Literal(t.value, datatype=URIRef(t.datatype.value)) if isinstance(t, ox.Literal) else t.value


def store(g: Graph) -> ox.Store:
    st = ox.Store()
    st.load(g.serialize(format="nt").encode(), ox.RdfFormat.N_TRIPLES)
    return st


def cq(onto: Path, g, name: str, bind: dict | None = None) -> list[dict]:
    """Rows of <onto>/cq/<name>.rq over g (rdflib Graph or pyoxigraph Store) with parameters bound."""
    text = (onto / "cq" / f"{name}.rq").read_text(encoding="utf-8")
    b = {**params(text), **(bind or {})}
    if b:
        if text.count("WHERE {") > 1:  # VALUES would land in the first (sub)query and bind the wrong scope
            raise ValueError(f"{name}: parameterized CQs must not contain subqueries")
        values = f"VALUES ({' '.join('?' + k for k in b)}) {{ ({' '.join(map(sparql_term, b.values()))}) }}"
        text = text.replace("WHERE {", "WHERE {\n  " + values, 1)
    res = (g if isinstance(g, ox.Store) else store(g)).query(text)
    names = [v.value for v in res.variables]
    return [{n: to_rdflib(row[n]) for n in names} for row in res]


def check(onto: Path, files, extra: str | None = None) -> dict:
    g = load(onto, files, extra)
    shapes = Graph()
    for f in sorted((onto / "shapes").glob("*.ttl")):
        shapes.parse(f)
    conforms, results, text = validate(g, shacl_graph=shapes)
    if not isinstance(results, Graph):  # pyshacl could not run the shapes themselves
        raise RuntimeError(f"SHACL shapes are invalid: {text}")
    violations = [f"{results.value(r, SH.focusNode)}: {results.value(r, SH.resultMessage)}"
                  for r in results.subjects(SH.focusNode, None)]
    st = store(g)
    for rule in sorted((onto / "shapes").glob("*.rq")):
        violations += [f"{r['focus'].value}: {r['message'].value}" for r in st.query(rule.read_text(encoding="utf-8"))]
    violations.sort()
    closed = Graph()
    closed += g
    owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(closed)  # ponytail: in-memory closure, fine for ~1e5 triples
    inconsistent = sorted(str(o) for o in closed.objects(None, OWLRL_ERROR))
    counts = {f.stem: len(cq(onto, st, f.stem)) for f in sorted((onto / "cq").glob("cq*.rq"))}
    return {"triples": len(g), "conforms": conforms and not violations, "violations": violations[:50],
            "n_violations": len(violations), "inconsistent": inconsistent, "cq_rows": counts}


def tools(onto) -> tuple:
    """(check, cq) bound to one ontology folder."""
    onto = Path(onto).resolve()
    return partial(check, onto), partial(cq, onto)


if __name__ == "__main__":
    print(json.dumps(check(Path(sys.argv[1]).resolve(), sys.argv[2:]), ensure_ascii=False, indent=1))
