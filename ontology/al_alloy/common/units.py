"""Printed units of measured values, shared by the extraction checker (icl paper-extract check_record.py) and the KG
builders (al6xxx/convert/build_kg.py), so a unit is added in one place.

UNITS: property kind -> unit as the paper prints it -> (low, high in that unit, unit the KG stores, factor to it).
The checker accepts exactly these units and ranges; the KG stores value x factor in the stored unit. QUDT has no
%IACS, mA/cm2, uA/cm2, nA/cm2, um/y, mpy, mg/(cm2 d) or ohm cm2: those are converted (100 %IACS = 58.0 MS/m, the
annealed copper standard; 1 mpy = 1 mil/year = 0.0254 mm/y; 1 um/h = 8.766 mm/y; 1 mg/(cm2 d) = 10/24 g/(m2 h));
ohm cm2 is al:OHM-CentiM2. normalize() turns the spellings papers use (uA cm-2, kΩ·cm², mm/a) into the table's.
A table column printed in scaled units ("icorr (10-4 A/cm2)") is written as printed; scaled() splits it.
"""
from __future__ import annotations

import re
from decimal import Decimal

D = Decimal
UNITS = {
    "CorrosionPotential": {"V": (-3, 1, "unit:V", D(1)), "mV": (-3000, 1000, "unit:MilliV", D(1))},
    "PittingPotential": {"V": (-3, 2, "unit:V", D(1)), "mV": (-3000, 2000, "unit:MilliV", D(1))},
    "CorrosionCurrentDensity": {"A/cm2": (0, 1, "unit:A-PER-CentiM2", D(1)),
                                "mA/cm2": (0, 1e3, "unit:A-PER-CentiM2", D("1e-3")),
                                "uA/cm2": (0, 1e6, "unit:A-PER-CentiM2", D("1e-6")),
                                "nA/cm2": (0, 1e9, "unit:A-PER-CentiM2", D("1e-9")),
                                "A/m2": (0, 1e4, "unit:A-PER-CentiM2", D("1e-4"))},
    "PolarizationResistance": {"ohm cm2": (0, 1e9, "al:OHM-CentiM2", D(1)),  # Rp or EIS Rct
                               "kohm cm2": (0, 1e6, "al:OHM-CentiM2", D("1e3"))},
    "CorrosionRate": {"mm/y": (-100, 1000, "unit:MilliM-PER-YR", D(1)),  # negative = mass gain, as some tables print
                      "um/y": (-1e5, 1e6, "unit:MilliM-PER-YR", D("1e-3")),
                      "mpy": (-4000, 40000, "unit:MilliM-PER-YR", D("0.0254")),
                      "um/h": (-1e4, 1e5, "unit:MilliM-PER-YR", D("8.766")),  # 8766 h a year
                      "g/(m2 h)": (-100, 1000, "unit:GM-PER-M2-HR", D(1)),
                      "mg/(cm2 d)": (-1000, 10000, "unit:GM-PER-M2-HR", D(10) / 24)},
    "CorrosionDepth": {"um": (0, 10000, "unit:MicroM", D(1))},
    "SCCSusceptibility": {"%": (0, 100, "unit:PERCENT", D(1))},
    "ElectricalConductivity": {"%IACS": (1, 110, "unit:MegaS-PER-M", D("0.58")),
                               "MS/m": (0.5, 65, "unit:MegaS-PER-M", D(1))},
}
CORROSION = [k for k in UNITS if k != "ElectricalConductivity"]  # kinds a corrosion test produces
STORED = {u: (s, f) for kinds in UNITS.values() for u, (_, _, s, f) in kinds.items()}  # one meaning per unit
SCALED = re.compile(r"(?:[×x]\s*)?10\s*\^?\s*([-−]?\d+)\s+(\S.*)")
ALIASES = {"mm/a": "mm/y", "mmpy": "mm/y", "mm/year": "mm/y", "mm y-1": "mm/y", "um/y": "um/y"}


def normalize(printed: str) -> str:
    """A paper's spelling of a unit in the table's form: µ/μ -> u, Ω -> ohm, ² -> 2, · or * -> space, "uA cm-2" ->
    "uA/cm2", "mm/a" -> "mm/y". Unknown units come back cleaned but otherwise unchanged (the checker refuses them)."""
    u = printed.strip().replace("µ", "u").replace("μ", "u").replace("Ω", "ohm").replace("²", "2").replace("−", "-")
    u = re.sub(r"\s+", " ", re.sub(r"\s*[·⋅*]\s*", " ", u))
    u = re.sub(r"^(\S+) cm-2$", r"\1/cm2", u)
    return ALIASES.get(u, u)


def scaled(printed: str) -> tuple[str, float]:
    """(base unit, factor) of a printed unit: "10-4 A/cm2" -> ("A/cm2", 1e-4), "mV" -> ("mV", 1)."""
    m = SCALED.fullmatch(printed.strip())
    return (m.group(2), 10.0 ** int(m.group(1).replace("−", "-"))) if m else (printed, 1.0)


def unit_of(printed: str) -> tuple[str, Decimal]:
    """(stored unit as prefix:name, exact factor from the printed unit to it), scaled columns included."""
    m = SCALED.fullmatch(printed.strip())
    if not m:
        return STORED[printed]
    unit, f = STORED[m.group(2)]
    return unit, f * D(10) ** int(m.group(1).replace("−", "-"))
