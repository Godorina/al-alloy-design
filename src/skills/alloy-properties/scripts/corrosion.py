"""Corrosion evidence for the final candidates: the alloy-strength KG evidence script, unchanged
(nearest measured or nominal alloys with a corrosion result, same temper, values per test), plus the
corrosion composition rules of each candidate. Evidence and rules, not predictions.

Usage:
  corrosion.py --spec '<spec JSON>' --candidates '<JSON list>' [--k 5]
"""
import contextlib
import io
import json
import sys

from props import corrosion_rules
from step0_checks import emit
import step3_corrosion as evidence


def main() -> None:
    buf = io.StringIO()
    code = 0
    try:
        with contextlib.redirect_stdout(buf):
            evidence.main()  # reads the same sys.argv; spec keys it does not know are ignored
    except SystemExit as e:  # evidence.fail() already wrote its error JSON
        code = e.code if isinstance(e.code, int) else 2
    doc = json.loads(buf.getvalue())
    if code == 0:
        for r in doc["results"]:
            r["corrosion_rules"] = corrosion_rules(r["composition"], doc["series"])
    emit(doc)
    sys.exit(code)


if __name__ == "__main__":
    main()
