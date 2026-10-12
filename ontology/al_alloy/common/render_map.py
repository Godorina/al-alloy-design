"""Concept map of an ontology folder's schema as Graphviz DOT, straight from schema/*.ttl.
Classes carry their datatype properties; arrows are object properties (domain -> range), hollow
arrows are subClassOf, notes list each SKOS scheme. Namespace and title come from the owl:Ontology
header (namespace = ontology IRI + '#').

Usage: ../icl/.venv/bin/python common/render_map.py <ontology dir> > map.dot   (then: dot -Tsvg)
"""
import sys
from pathlib import Path

from rdflib import OWL, RDF, RDFS, Graph
from rdflib.namespace import DCTERMS, SKOS

from check import schema_files

EXT = {"http://www.w3.org/ns/prov#": "prov:", "https://schema.org/": "schema:",
       "http://www.w3.org/2004/02/skos/core#": "skos:"}


def ko(g, x, p=RDFS.label) -> str:
    return next((str(o) for o in g.objects(x, p) if o.language == "ko"), "")


def dot(g: Graph) -> str:
    onto = next(g.subjects(RDF.type, OWL.Ontology))
    ns = str(onto) + "#"
    pfx = {ns: "", **EXT}
    short = lambda x: next((p + str(x)[len(n):] for n, p in pfx.items() if str(x).startswith(n)), str(x))  # noqa: E731
    mine = lambda x: str(x).startswith(ns)  # noqa: E731
    title = f"{ko(g, onto, DCTERMS.title)} v{g.value(onto, OWL.versionInfo)} 개념 지도 (schema/*.ttl에서 자동 생성)"
    out = ['digraph onto {', '  rankdir=LR; fontname="Helvetica"; node [fontname="Helvetica", fontsize=10];',
           '  edge [fontname="Helvetica", fontsize=9];',
           f'  label="{title} · 실선: 관계(domain→range) · 속빈 화살표: 하위 클래스 · 점선: 값 목록"; labelloc=t;']
    classes = sorted(c for c in g.subjects(RDF.type, OWL.Class) if mine(c))
    for c in classes:
        dps = sorted(f"{short(p)} ({ko(g, p)})" for p in g.subjects(RDFS.domain, c)
                     if (p, RDF.type, OWL.DatatypeProperty) in g)
        rows = "".join(f'<TR><TD ALIGN="LEFT"><FONT POINT-SIZE="9">{d}</FONT></TD></TR>' for d in dps)
        out.append(f'  "{short(c)}" [shape=plaintext, label=<<TABLE BORDER="1" CELLBORDER="0" BGCOLOR="#eef4ff">'
                   f'<TR><TD><B>{short(c)}</B><BR/>{ko(g, c)}</TD></TR>{rows}</TABLE>>];')
        for sup in g.objects(c, RDFS.subClassOf):
            if not mine(sup):
                out.append(f'  "{short(sup)}" [shape=box, style="rounded,filled", fillcolor="#eeeeee", fontcolor="#666666"];')
            out.append(f'  "{short(c)}" -> "{short(sup)}" [arrowhead=empty, color="#888888"];')
    for s in sorted(g.subjects(RDF.type, SKOS.ConceptScheme)):
        items = sorted(str(next(iter(g.objects(c, SKOS.notation)), "")) or short(c) for c in g.subjects(SKOS.inScheme, s))
        out.append(f'  "{short(s)}" [shape=note, style=filled, fillcolor="#fff6d5", '
                   f'label="{short(s)} ({ko(g, s)})\\n{" · ".join(items)}"];')
    scheme = lambda c: set(g.objects(c, SKOS.inScheme))  # noqa: E731
    for p in sorted(p for p in g.subjects(RDF.type, OWL.ObjectProperty) if mine(p)):
        for d in g.objects(p, RDFS.domain):
            for r in g.objects(p, RDFS.range):
                if r != SKOS.Concept:
                    out.append(f'  "{short(d)}" -> "{short(r)}" [label="{short(p)}"];')
                elif d == SKOS.Concept:  # concept -> concept: draw scheme -> scheme from the vocabulary data
                    for a, b in sorted({(x, y) for s, o in g.subject_objects(p) for x in scheme(s) for y in scheme(o)}):
                        out.append(f'  "{short(a)}" -> "{short(b)}" [style=dashed, label="{short(p)}"];')
                else:  # values come from the scheme named by rdfs:seeAlso
                    for s in g.objects(p, RDFS.seeAlso):
                        out.append(f'  "{short(d)}" -> "{short(s)}" [style=dashed, label="{short(p)}"];')
    return "\n".join(out + ["}"])


if __name__ == "__main__":
    g = Graph()
    for f in schema_files(Path(sys.argv[1]).resolve()):
        g.parse(f)
    text = dot(g)
    assert text.count("->") > 5  # self-check: edges were drawn
    print(text)
