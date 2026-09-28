import math

from app.core import geometry as g
from app.core.symbols import (
    classify_block, looks_like_tag, next_free_tag, next_line_tag, normalize_tag, prefix_type, tag_valid_for_type,
)


def test_normalize_and_classify_tags():
    assert normalize_tag("p101") == "P-101"
    assert normalize_tag("pt 102") == "PT-102"
    assert normalize_tag("FT_101a") == "FT-101A"
    assert prefix_type("P") == "pump"
    assert prefix_type("TK") == "tank"
    assert prefix_type("FV") == "control_valve"
    assert prefix_type("FT") == "instrument"
    assert prefix_type("LIC") == "instrument_panel"
    assert prefix_type("PSV") == "relief_valve"
    assert prefix_type("XYZ") is None
    assert looks_like_tag("pt102") and not looks_like_tag("NOTES:")
    assert tag_valid_for_type("P-101", "pump") and not tag_valid_for_type("TK-101", "pump")
    assert tag_valid_for_type("LT-101", "instrument") and not tag_valid_for_type("P-101", "instrument")


def test_block_classification():
    assert classify_block("CENTRIFUGAL_PUMP") == "pump"
    assert classify_block("VALVE-GATE-2IN") == "gate_valve"
    assert classify_block("NRV") == "check_valve"
    assert classify_block("ISA_INSTR_BUBBLE") == "instrument"
    assert classify_block("A3_TITLE") == "title_block"
    assert classify_block("NORTH_ARROW") is None


def test_tag_series():
    assert next_free_tag("P", {"P-101", "P-102"}, start=101) == "P-103"
    assert next_line_tag(["50-RW-1001", "50-RW-1002", "80-TW-1005"]) == "50-RW-1006"
    assert next_line_tag(["50-RW-1001"], hint_head="80-TW-") == "80-TW-1002"
    assert next_line_tag([]) == "L-001"


def test_geometry_helpers():
    assert g.seg_bbox_clip([0, 5], [10, 5], [2, 0, 4, 10]) == (0.2, 0.4)
    assert g.seg_bbox_clip([0, 20], [10, 20], [2, 0, 4, 10]) is None
    assert g.orthogonal_route([0, 0], [10, 6]) == [[0, 0], [5, 0], [5, 6], [10, 6]]
    assert g.simplify_polyline([[0, 0], [5, 0], [10, 0], [10, 0]]) == [[0, 0], [10, 0]]
    c, r, a0, a1 = g.bulge_arc([0, 0], [2, 0], 1.0)  # semicircle, counter-clockwise -> dips below the chord
    assert math.isclose(r, 1) and math.isclose(c[0], 1) and abs(c[1]) < 1e-9
    mid_angle = math.radians(a0 + ((a1 - a0) % 360) / 2)
    assert c[1] + r * math.sin(mid_angle) < 0
