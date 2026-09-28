import copy

from app.core.ops import apply_ops
from app.rules.engine import catalog, run_rules
from app.samples import water_treatment
from app.services import autofix_doc
from tests.conftest import by_tag

SEEDED = ["R001", "R002", "R006", "R007", "R009", "R010", "R011", "R013", "R014"]


def rule_ids(doc):
    return sorted(f["rule_id"] for f in run_rules(doc))


def test_catalog_has_15_rules():
    ids = [r["id"] for r in catalog()]
    assert ids == [f"R{n:03d}" for n in range(1, 16)]


def test_every_seeded_error_is_found(faulty):
    assert rule_ids(faulty) == SEEDED


def test_clean_drawing_passes(clean):
    assert run_rules(clean) == []


def test_finding_shape(faulty):
    f = next(f for f in run_rules(faulty) if f["rule_id"] == "R001")
    assert f["key"].startswith("R001:") and f["source"] == "rule"
    assert f["bbox"] and f["location"] and f["fix"]["ops"][0] == {"op": "set_tag", "id": f["entities"][0], "tag": "P-102"}


def test_autofix_leaves_only_judgement_calls(faulty):
    fixed, ops, messages, changed = autofix_doc(faulty)
    assert rule_ids(fixed) == ["R011", "R014"]
    assert len(ops) >= 7 and changed


def test_prefix_mismatch_untagged_and_overlap(clean):
    doc = copy.deepcopy(clean)
    pump = by_tag(doc, "P-102")[0]
    pump["tag"] = "TK-102"
    ft = by_tag(doc, "FT-101")[0]
    ft["tag"] = None
    lg = by_tag(doc, "LG-101")[0]
    v = by_tag(doc, "V-101")[0]
    lg["x"], lg["y"] = v["x"] - 3, v["y"]
    found = {f["rule_id"]: f for f in run_rules(doc)}
    assert found["R003"]["fix"]["ops"][0]["tag"] == "P-102"
    assert "R004" in found and found["R004"]["fix"] is None  # instruments need a measured-variable prefix
    assert "R015" in found and found["R015"]["fix"]["ops"][0]["op"] == "move"


def test_unconnected_equipment_and_instrument(clean):
    res = apply_ops(clean, [
        {"op": "add_entity", "type": "heat_exchanger", "tag": "E-101", "x": 120, "y": 240},
        {"op": "add_entity", "type": "instrument", "tag": "TT-101", "x": 160, "y": 240},
    ])
    ids = rule_ids(res.doc)
    assert "R005" in ids and "R012" in ids


def test_pump_isolation_rule(clean):
    hv = by_tag(clean, "HV-101")[0]
    res = apply_ops(clean, [{"op": "delete", "id": hv["id"]}])
    found = [f for f in run_rules(res.doc) if f["rule_id"] == "R008"]
    assert len(found) == 1 and "suction" in found[0]["title"]
    fixed = apply_ops(res.doc, found[0]["fix"]["ops"]).doc
    assert "R008" not in rule_ids(fixed)


def test_missing_title_block(clean):
    doc = copy.deepcopy(clean)
    doc["title_block"] = None
    assert rule_ids(doc) == ["R014"]


def test_pdf_documents_skip_topology_rules(faulty):
    doc = copy.deepcopy(faulty)
    doc["meta"]["connectivity"] = False
    ids = rule_ids(doc)
    assert not {"R005", "R006", "R007", "R008", "R012", "R013"} & set(ids)
    assert {"R001", "R002", "R009", "R010", "R011", "R014"} <= set(ids)


def test_rules_are_stable_for_regenerated_sample():
    assert [f["key"] for f in run_rules(water_treatment())] == [f["key"] for f in run_rules(water_treatment())]


def test_loop_wiring_and_field_instrument_process_connection(clean):
    lic = by_tag(clean, "LIC-102")[0]
    lt = by_tag(clean, "LT-101")[0]
    tk = by_tag(clean, "TK-101")[0]
    # drop the LIC-102 -> LV-102 signal line and LT-101's nozzle line, then add a signal-only transmitter
    doc = apply_ops(clean, [
        {"op": "delete", "id": next(ln["id"] for ln in clean["lines"] if ln["kind"] == "signal" and ln["pts"][0][0] == 370)},
        {"op": "delete", "id": next(ln["id"] for ln in clean["lines"] if ln["pts"][0] == [67.0, 183.0])},
        {"op": "connect", "from": lt["id"], "to": lic["id"], "kind": "signal"},
    ]).doc
    found = {f["rule_id"]: f for f in run_rules(doc)}
    assert found["R011"]["title"] == "LV-102 is not wired to its control loop"
    assert found["R012"]["title"] == "LT-101 has no process connection"
    assert found["R012"]["fix"]["ops"][0]["from"] == tk["id"]
    fixed, *_ = autofix_doc(doc)
    assert not {"R011", "R012"} & set(rule_ids(fixed))
