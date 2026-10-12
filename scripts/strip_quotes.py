#!/usr/bin/env python3
"""Remove the verbatim paper quotes (al:quote, ml:quote) from a knowledge graph before publishing it.

Usage: .venv/bin/python scripts/strip_quotes.py ontology/al_alloy/al6xxx/build/kg.ttl [...]
Evidence nodes keep their DOI link and page; only the copied source text is dropped. Idempotent.
"""
import sys

from rdflib import Graph, URIRef

QUOTES = (URIRef("https://w3id.org/al6xxx#quote"), URIRef("https://w3id.org/alml#quote"))


def main(paths: list[str]) -> None:
    for path in paths:
        g = Graph()
        g.parse(path, format="turtle")
        dropped = 0
        for p in QUOTES:
            for t in list(g.triples((None, p, None))):
                g.remove(t)
                dropped += 1
        g.serialize(path, format="turtle")
        print(f"{path}: removed {dropped} quote triples, {len(g)} triples left")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
