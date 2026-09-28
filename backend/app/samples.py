"""Sample P&ID used by the live demo and the tests.

`water_treatment(errors=True)` builds an A3 raw-water transfer & filtration P&ID with these seeded
defects (the rule that should catch each is in brackets):

  1. standby pump tagged P-101, duplicating the duty pump            [R001]
  2. standby pump discharge has no check valve                        [R007]
  3. raw water tank TK-101 has no level instrument                    [R009]
  4. pressure vessel V-101 has no pressure safety valve               [R010]
  5. pressure transmitter tagged "pt102"                              [R002]
  6. filter outlet line stops 4 mm short of V-101                     [R006]
  7. LV-102 has no LT-102 / LIC-102 loop instruments                  [R011]
  8. vessel outlet run has no line number                             [R013]
  9. title block "CHECKED" field left blank                           [R014]
"""
from __future__ import annotations

import copy

from .core import geometry as g
from .core.document import empty_document, new_id, recompute_bounds
from .core.symbols import BUILTIN_BLOCKS, TITLE_FIELD_POS, TYPES, category, default_label

H = 2.5


def _ent(doc, type_, tag, x, y, rot=0.0, label=None):
    block = TYPES[type_]["block"]
    doc["blocks"].setdefault(block, copy.deepcopy(BUILTIN_BLOCKS[block]))
    ent = {"id": new_id(doc, "E"), "type": type_, "tag": tag, "block": block, "x": float(x), "y": float(y),
           "rot": float(rot), "sx": 1.0, "sy": 1.0, "layer": category(type_).upper(), "attrs": {}}
    ent["label"] = default_label(type_, g.bbox_of(doc["blocks"][block]), H) if tag else None
    if label and ent["label"]:
        ent["label"].update(label)
    doc["entities"].append(ent)
    return ent["id"]


def _line(doc, pts, kind="process", tag=None):
    ln = {"id": new_id(doc, "L"), "kind": kind, "pts": [[float(x), float(y)] for x, y in pts], "tag": tag,
          "layer": "PIPING" if kind == "process" else "SIGNAL", "tag_pos": None}
    doc["lines"].append(ln)
    return ln["id"]


def _text(doc, s, x, y, h=H, ha="left", layer="NOTES"):
    doc["background"].append({"t": "text", "p": [x, y], "s": s, "h": h, "rot": 0, "ha": ha, "va": "baseline",
                              "layer": layer})


def water_treatment(errors: bool = True) -> dict:
    doc = empty_document("dxf", "mm")

    # sheet
    doc["background"].append({"t": "poly", "pts": [[10, 10], [410, 10], [410, 287], [10, 287]], "closed": True,
                              "layer": "BORDER"})
    _text(doc, "RAW WATER TRANSFER & FILTRATION", 20, 272, h=5, layer="TITLE_TEXT")
    _text(doc, "PIPING & INSTRUMENTATION DIAGRAM", 20, 265, h=3, layer="TITLE_TEXT")
    _text(doc, "NOTES:", 20, 62, h=2.5)
    _text(doc, "1. ALL LINE SIZES IN MM.", 20, 57, h=2.2)
    _text(doc, "2. P-101 DUTY / STANDBY PUMP SET.", 20, 52.5, h=2.2)
    _text(doc, "3. INSTRUMENT TAGS PER ISA-5.1.", 20, 48, h=2.2)

    # raw water tank and suction header
    tk = _ent(doc, "tank", "TK-101", 55, 170)
    _line(doc, [(67, 160), (90, 160)], tag="100-RW-1001")
    _line(doc, [(90, 160), (90, 200), (103, 200)], tag="80-RW-1002")
    _line(doc, [(90, 160), (90, 130), (103, 130)], tag="80-RW-1003")

    # duty pump
    _ent(doc, "gate_valve", "HV-101", 108, 200)
    _line(doc, [(113, 200), (129, 200)])
    _ent(doc, "pump", "P-101", 135, 200)
    _line(doc, [(141, 200), (151, 200)])
    _ent(doc, "check_valve", "NRV-101", 156, 200)
    _line(doc, [(161, 200), (171, 200)])
    _ent(doc, "gate_valve", "HV-102", 176, 200)
    _line(doc, [(181, 200), (200, 200), (200, 165)], tag="80-RW-1004")

    # standby pump
    _ent(doc, "gate_valve", "HV-103", 108, 130)
    _line(doc, [(113, 130), (129, 130)])
    _ent(doc, "pump", "P-101" if errors else "P-102", 135, 130)
    if errors:
        _line(doc, [(141, 130), (171, 130)])
    else:
        _line(doc, [(141, 130), (151, 130)])
        _ent(doc, "check_valve", "NRV-102", 156, 130)
        _line(doc, [(161, 130), (171, 130)])
    _ent(doc, "gate_valve", "HV-104", 176, 130)
    _line(doc, [(181, 130), (200, 130), (200, 165)], tag="80-RW-1005")

    # flow control loop
    _line(doc, [(200, 165), (235, 165)], tag="100-RW-1006")
    _ent(doc, "instrument", "FT-101", 220, 185)
    _line(doc, [(220, 165), (220, 180)])
    _ent(doc, "instrument_panel", "FIC-101", 240, 212)
    _line(doc, [(220, 190), (220, 212), (235, 212)], kind="signal")
    _line(doc, [(240, 207), (240, 176)], kind="signal")
    _ent(doc, "control_valve", "FV-101", 240, 165, label={"dx": 12.0, "dy": 7.0})

    # filter and pressure vessel
    _line(doc, [(245, 165), (268, 165)])
    _ent(doc, "filter", "FL-101", 275, 165)
    _line(doc, [(282, 165), (332 if errors else 336, 165)], tag="100-TW-1007")
    v = _ent(doc, "vessel", "V-101", 345, 180)
    _ent(doc, "instrument", "LG-101", 325, 200)
    _line(doc, [(336, 200), (330, 200)])
    _ent(doc, "instrument", "pt102" if errors else "PT-102", 370, 195)
    _line(doc, [(354, 195), (365, 195)])

    # vessel outlet to off-page
    _line(doc, [(345, 157), (345, 120), (365, 120)], tag=None if errors else "80-TW-1008")
    _ent(doc, "control_valve", "LV-102", 370, 120, label={"dx": 0.0, "dy": -7.5})
    _line(doc, [(375, 120), (386, 120)])
    _ent(doc, "off_page", None, 395, 120)
    _text(doc, "TO WT-P-002", 395, 127, h=2.2, ha="center")

    if not errors:
        lt = _ent(doc, "instrument", "LT-101", 79, 183)
        _line(doc, [(67, 183), (74, 183)])
        psv = _ent(doc, "relief_valve", "PSV-101", 345, 223)
        _line(doc, [(345, 203), (345, 217)])
        _ent(doc, "instrument_panel", "LIC-102", 370, 150)
        _line(doc, [(370, 145), (370, 131)], kind="signal")
        del lt, psv

    # title block
    doc["blocks"]["TITLE_BLOCK"] = copy.deepcopy(BUILTIN_BLOCKS["TITLE_BLOCK"])
    values = {"TITLE": "RAW WATER TRANSFER & FILTRATION", "DWG_NO": "WT-P-001", "REV": "B",
              "DRAWN_BY": "A. ENGINEER", "CHECKED_BY": "" if errors else "LEAD CHECKER", "DATE": "2026-09-27"}
    doc["title_block"] = {"block": "TITLE_BLOCK", "x": 230.0, "y": 10.0, "sx": 1.0, "sy": 1.0, "rot": 0.0, "fields": {
        k: {"value": val, "p": [230 + TITLE_FIELD_POS[k][0], 10 + TITLE_FIELD_POS[k][1]], "h": TITLE_FIELD_POS[k][2]}
        for k, val in values.items()}}
    del tk, v
    recompute_bounds(doc)
    return doc
