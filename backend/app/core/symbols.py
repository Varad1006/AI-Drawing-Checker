"""P&ID symbol library and tagging conventions (ISA-5.1 style).

Everything that knows what a "pump" or an "FT-101" is lives here, so parsers, rules, the editor and the
AI tools all agree on the same vocabulary.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------------------------------
# Component types
# ---------------------------------------------------------------------------------------------------

TYPES: dict[str, dict] = {
    # equipment
    "pump":             {"category": "equipment",  "block": "PUMP",           "prefixes": ["P"],   "name": "Centrifugal pump"},
    "tank":             {"category": "equipment",  "block": "TANK",           "prefixes": ["TK"],  "name": "Atmospheric tank"},
    "vessel":           {"category": "equipment",  "block": "VESSEL",         "prefixes": ["V"],   "name": "Pressure vessel"},
    "heat_exchanger":   {"category": "equipment",  "block": "HEAT_EXCHANGER", "prefixes": ["E"],   "name": "Heat exchanger"},
    "filter":           {"category": "equipment",  "block": "FILTER",         "prefixes": ["FL"],  "name": "Filter"},
    # inline valves
    "gate_valve":       {"category": "valve",      "block": "GATE_VALVE",     "prefixes": ["HV"],  "name": "Gate valve"},
    "globe_valve":      {"category": "valve",      "block": "GLOBE_VALVE",    "prefixes": ["HV"],  "name": "Globe valve"},
    "ball_valve":       {"category": "valve",      "block": "BALL_VALVE",     "prefixes": ["HV"],  "name": "Ball valve"},
    "check_valve":      {"category": "valve",      "block": "CHECK_VALVE",    "prefixes": ["NRV"], "name": "Check valve"},
    "control_valve":    {"category": "valve",      "block": "CONTROL_VALVE",  "prefixes": ["FV", "LV", "PV", "TV", "XV"], "name": "Control valve"},
    "relief_valve":     {"category": "valve",      "block": "RELIEF_VALVE",   "prefixes": ["PSV", "PRV"], "name": "Pressure safety valve"},
    # instruments
    "instrument":       {"category": "instrument", "block": "INSTRUMENT",       "prefixes": [], "name": "Field instrument"},
    "instrument_panel": {"category": "instrument", "block": "INSTRUMENT_PANEL", "prefixes": [], "name": "Panel instrument / controller"},
    # annotation
    "off_page":         {"category": "connector",  "block": "OFF_PAGE",       "prefixes": [],      "name": "Off-page connector"},
}

ISOLATION_VALVES = {"gate_valve", "globe_valve", "ball_valve"}
LEVEL_HOLDING = {"tank", "vessel"}


def category(type_: str) -> str:
    return TYPES.get(type_, {}).get("category", "other")


def needs_tag(type_: str) -> bool:
    """Manual valves are commonly untagged on P&IDs; everything else should carry a tag."""
    return category(type_) in ("equipment", "instrument") or type_ in ("control_valve", "relief_valve")


# Block-name keywords -> type. Order matters: the first match wins.
BLOCK_PATTERNS: list[tuple[str, str]] = [
    (r"TITLE", "title_block"),
    (r"OFF.?PAGE|\bOPC\b|CONNECTOR", "off_page"),
    (r"PSV|PRV|RELIEF|SAFETY", "relief_valve"),
    (r"CONTROL.?V|CTRL.?V|^CV$|ACTUATED", "control_valve"),
    (r"CHECK|NRV|NON.?RETURN", "check_valve"),
    (r"GLOBE", "globe_valve"),
    (r"BALL", "ball_valve"),
    (r"GATE|VALVE", "gate_valve"),
    (r"PUMP", "pump"),
    (r"TANK", "tank"),
    (r"VESSEL|DRUM|COLUMN|TOWER|REACTOR", "vessel"),
    (r"EXCH|^HX|COOLER|HEATER", "heat_exchanger"),
    (r"FILTER|STRAINER", "filter"),
    (r"PANEL|CONTROLLER|DCS", "instrument_panel"),
    (r"INSTR|BUBBLE|TRANSMITTER|GAUGE|INDICATOR", "instrument"),
]


def classify_block(name: str) -> str | None:
    n = name.upper()
    for pattern, type_ in BLOCK_PATTERNS:
        if re.search(pattern, n):
            return type_
    return None


# ---------------------------------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------------------------------

TAG_RE = re.compile(r"^([A-Z]{1,4})-(\d{2,4})([A-Z])?$")
LOOSE_TAG_RE = re.compile(r"^([A-Za-z]{1,4})[\s_\-]?(\d{2,4})([A-Za-z])?$")
LINE_TAG_RE = re.compile(r'^(\d+(?:\.\d+)?"?-[A-Z]{1,3}-)(\d{3,4})(-[A-Z0-9]{1,4})?$|^(L-)(\d{3,4})()$')

MEASURED_VARIABLES = set("AFLPT")          # analysis, flow, level, pressure, temperature
FUNCTION_LETTERS = set("CEGIRSTYHLAV")     # controller, element, gauge, indicator, recorder, switch, transmitter…


def _valve_and_equipment_prefixes() -> dict[str, str]:
    out: dict[str, str] = {}
    for type_, meta in TYPES.items():
        for prefix in meta["prefixes"]:
            out.setdefault(prefix, type_)
    return out


PREFIX_TYPES = _valve_and_equipment_prefixes()


def is_instrument_prefix(prefix: str) -> bool:
    return (
        prefix not in PREFIX_TYPES
        and 2 <= len(prefix) <= 4
        and prefix[0] in MEASURED_VARIABLES
        and all(c in FUNCTION_LETTERS for c in prefix[1:])
    )


def prefix_type(prefix: str) -> str | None:
    prefix = prefix.upper()
    if prefix in PREFIX_TYPES:
        return PREFIX_TYPES[prefix]
    if is_instrument_prefix(prefix):
        return "instrument_panel" if prefix.endswith("C") else "instrument"
    return None


def parse_tag(tag: str | None) -> tuple[str, int, str] | None:
    """'FT-101A' -> ('FT', 101, 'A'); None when not in canonical form."""
    if not tag:
        return None
    m = TAG_RE.match(tag)
    if not m:
        return None
    return m.group(1), int(m.group(2)), m.group(3) or ""


def looks_like_tag(text: str) -> bool:
    return bool(LOOSE_TAG_RE.match(text.strip())) and prefix_type(LOOSE_TAG_RE.match(text.strip()).group(1)) is not None


def normalize_tag(text: str) -> str:
    """'p101' / 'P 101' / 'P_101' -> 'P-101'. Returns the input unchanged if it is not tag-like."""
    m = LOOSE_TAG_RE.match(text.strip())
    if not m:
        return text
    return f"{m.group(1).upper()}-{m.group(2)}{(m.group(3) or '').upper()}"


def tag_valid_for_type(tag: str, type_: str) -> bool:
    parsed = parse_tag(tag)
    if not parsed:
        return False
    prefix = parsed[0]
    if category(type_) == "instrument":
        return is_instrument_prefix(prefix)
    allowed = TYPES.get(type_, {}).get("prefixes", [])
    return not allowed or prefix in allowed


def default_prefix(type_: str) -> str | None:
    prefixes = TYPES.get(type_, {}).get("prefixes") or []
    return prefixes[0] if prefixes else None


def next_free_tag(prefix: str, existing: set[str], start: int = 101, width: int = 3) -> str:
    n = max(start, 1)
    while f"{prefix}-{n:0{width}d}" in existing:
        n += 1
    return f"{prefix}-{n:0{width}d}"


def line_tag_head(tag: str | None) -> str | None:
    m = LINE_TAG_RE.match(tag or "")
    if not m:
        return None
    return m.group(1) or m.group(4)


def next_line_tag(existing: list[str], hint_head: str | None = None) -> str:
    """Next line number: sequence unique across the drawing, prefix (size-service) from the hint or the
    drawing's most common series. 50-RW-1003 + hint '80-TW-' -> 80-TW-1004."""
    heads: dict[str, int] = {}
    seqs, width = [], 3
    for tag in existing:
        m = LINE_TAG_RE.match(tag or "")
        if not m:
            continue
        head, num = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(5))
        heads[head] = heads.get(head, 0) + 1
        seqs.append(int(num))
        width = len(num)
    if not heads:
        return next_free_tag("L", set(existing), start=1)
    head = hint_head or max(heads, key=lambda h: heads[h])
    used = set(existing)
    n = max(seqs) + 1
    while f"{head}{n:0{width}d}" in used:
        n += 1
    return f"{head}{n:0{width}d}"


# ---------------------------------------------------------------------------------------------------
# Built-in block geometry (block-local, millimetres, insertion point at the symbol's centre)
# ---------------------------------------------------------------------------------------------------

def _rect(x0, y0, x1, y1, **kw):
    return {"t": "poly", "pts": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "closed": True, **kw}


def _bowtie(w=5.0, h=3.0):
    return {"t": "poly", "pts": [[-w, h], [-w, -h], [w, h], [w, -h]], "closed": True}


BUILTIN_BLOCKS: dict[str, list[dict]] = {
    "PUMP": [
        {"t": "circle", "c": [0, 0], "r": 6},
        {"t": "line", "a": [0, 6], "b": [6, 6]},
        {"t": "poly", "pts": [[-4.2, -4.2], [-6, -8], [6, -8], [4.2, -4.2]], "closed": False},
        {"t": "poly", "pts": [[-2.5, -3], [3.5, 0], [-2.5, 3]], "closed": True},
    ],
    "TANK": [
        _rect(-12, -15, 12, 15),
        {"t": "poly", "pts": [[-12, 15], [0, 19], [12, 15]], "closed": False},
    ],
    "VESSEL": [
        {"t": "line", "a": [-9, -14], "b": [-9, 14]},
        {"t": "line", "a": [9, -14], "b": [9, 14]},
        {"t": "arc", "c": [0, 14], "r": 9, "a0": 0, "a1": 180},
        {"t": "arc", "c": [0, -14], "r": 9, "a0": 180, "a1": 360},
    ],
    "HEAT_EXCHANGER": [
        {"t": "circle", "c": [0, 0], "r": 7},
        {"t": "poly", "pts": [[-7, 0], [-3.5, 4], [0, -4], [3.5, 4], [7, 0]], "closed": False},
    ],
    "FILTER": [
        _rect(-7, -10, 7, 10),
        {"t": "line", "a": [-7, -10], "b": [7, 10], "ls": "dashed"},
    ],
    "GATE_VALVE": [_bowtie()],
    "GLOBE_VALVE": [_bowtie(), {"t": "circle", "c": [0, 0], "r": 1.4, "fill": True}],
    "BALL_VALVE": [_bowtie(), {"t": "circle", "c": [0, 0], "r": 1.9}],
    "CHECK_VALVE": [
        _bowtie(),
        {"t": "poly", "pts": [[5, 3], [5, -3], [0, 0]], "closed": True, "fill": True},
    ],
    "CONTROL_VALVE": [
        _bowtie(),
        {"t": "line", "a": [0, 0], "b": [0, 7]},
        {"t": "arc", "c": [0, 7], "r": 4, "a0": 0, "a1": 180},
        {"t": "line", "a": [-4, 7], "b": [4, 7]},
    ],
    "RELIEF_VALVE": [
        {"t": "poly", "pts": [[-3, -6], [3, -6], [0, 0]], "closed": True},
        {"t": "poly", "pts": [[6, -3], [6, 3], [0, 0]], "closed": True},
        {"t": "poly", "pts": [[0, 0], [0, 2], [-2, 3], [2, 4], [-2, 5], [2, 6], [0, 7]], "closed": False},
    ],
    "INSTRUMENT": [{"t": "circle", "c": [0, 0], "r": 5}],
    "INSTRUMENT_PANEL": [
        {"t": "circle", "c": [0, 0], "r": 5},
        {"t": "line", "a": [-5, 0], "b": [5, 0]},
    ],
    "OFF_PAGE": [
        {"t": "poly", "pts": [[-9, -3], [5, -3], [9, 0], [5, 3], [-9, 3]], "closed": True},
    ],
}

TITLE_FIELDS = ["TITLE", "DWG_NO", "REV", "DRAWN_BY", "CHECKED_BY", "DATE"]
TITLE_FIELD_LABELS = {
    "TITLE": "TITLE", "DWG_NO": "DWG NO", "REV": "REV", "DRAWN_BY": "DRAWN", "CHECKED_BY": "CHECKED", "DATE": "DATE",
}

# 180 x 40 title block, insertion point bottom-left. Field values are placed at TITLE_FIELD_POS.
BUILTIN_BLOCKS["TITLE_BLOCK"] = [
    _rect(0, 0, 180, 40),
    {"t": "line", "a": [0, 22], "b": [180, 22]},
    {"t": "line", "a": [0, 11], "b": [180, 11]},
    {"t": "line", "a": [90, 0], "b": [90, 22]},
    {"t": "line", "a": [140, 11], "b": [140, 22]},
    {"t": "line", "a": [45, 0], "b": [45, 11]},
    {"t": "line", "a": [135, 0], "b": [135, 11]},
    {"t": "text", "p": [2, 36.5], "s": "TITLE", "h": 1.8, "rot": 0, "ha": "left", "va": "baseline"},
    {"t": "text", "p": [2, 19], "s": "DWG NO", "h": 1.8, "rot": 0, "ha": "left", "va": "baseline"},
    {"t": "text", "p": [92, 19], "s": "CLIENT / PROJECT", "h": 1.8, "rot": 0, "ha": "left", "va": "baseline"},
    {"t": "text", "p": [142, 19], "s": "REV", "h": 1.8, "rot": 0, "ha": "left", "va": "baseline"},
    {"t": "text", "p": [2, 8], "s": "DRAWN", "h": 1.8, "rot": 0, "ha": "left", "va": "baseline"},
    {"t": "text", "p": [47, 8], "s": "CHECKED", "h": 1.8, "rot": 0, "ha": "left", "va": "baseline"},
    {"t": "text", "p": [92, 8], "s": "DATE", "h": 1.8, "rot": 0, "ha": "left", "va": "baseline"},
    {"t": "text", "p": [137, 8], "s": "SCALE  NTS", "h": 1.8, "rot": 0, "ha": "left", "va": "baseline"},
]
TITLE_FIELD_POS = {
    "TITLE": [4, 27, 3.2], "DWG_NO": [4, 13.5, 3.0], "REV": [150, 13.5, 3.0],
    "DRAWN_BY": [4, 2.5, 2.8], "CHECKED_BY": [49, 2.5, 2.8], "DATE": [94, 2.5, 2.8],
}


def default_label(type_: str, local_box: list[float], h: float = 2.5) -> dict:
    """Where a new component's tag goes, as an offset from its insertion point."""
    cat = category(type_)
    if cat == "instrument":
        return {"dx": 0.0, "dy": 0.0, "h": h * 0.8, "rot": 0, "style": "split"}
    if cat == "valve":
        return {"dx": 0.0, "dy": local_box[3] + 2.0, "h": h * 0.9, "rot": 0, "style": "single"}
    return {"dx": 0.0, "dy": local_box[1] - h - 2.5, "h": h * 1.1, "rot": 0, "style": "single"}
