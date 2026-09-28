import pytest

from app.core import topology
from app.core.document import entity_bbox, find_line
from app.core.ops import OpError, apply_ops
from tests.conftest import by_tag


def test_set_tag_by_id_and_ambiguous_tag(faulty):
    with pytest.raises(OpError, match="used by 2 components"):
        apply_ops(faulty, [{"op": "set_tag", "id": "P-101", "tag": "P-102"}])
    dup = by_tag(faulty, "P-101")[1]
    res = apply_ops(faulty, [{"op": "set_tag", "id": dup["id"], "tag": "P-102"}])
    assert len(by_tag(res.doc, "P-102")) == 1 and dup["id"] in res.changed


def test_move_drags_attached_pipes(clean):
    pump = by_tag(clean, "P-101")[0]
    res = apply_ops(clean, [{"op": "move", "id": "P-101", "dx": 0, "dy": 10}])
    topo = topology.build(res.doc)
    assert topo.is_connected(pump["id"], "process") and not topo.dangling
    for lid, _ in topo.attachments[pump["id"]]:
        pts = find_line(res.doc, lid)["pts"]
        assert all(abs(a[0] - b[0]) < 1e-6 or abs(a[1] - b[1]) < 1e-6 for a, b in zip(pts, pts[1:])), "stays orthogonal"


def test_insert_inline_splits_pipe(faulty):
    pump = by_tag(faulty, "P-101")[1]
    before = len(faulty["lines"])
    res = apply_ops(faulty, [{"op": "insert_inline", "type": "check_valve", "after": pump["id"]}])
    nrv = by_tag(res.doc, "NRV-102")[0]
    assert len(res.doc["lines"]) == before + 1
    topo = topology.build(res.doc)
    assert pump["id"] in topo.neighbours(nrv["id"])
    assert not topo.dangling or all(d[0] == "L16" for d in topo.dangling)


def test_delete_inline_valve_rejoins_pipe(clean):
    nrv = by_tag(clean, "NRV-101")[0]
    res = apply_ops(clean, [{"op": "delete", "id": nrv["id"]}])
    topo = topology.build(res.doc)
    assert len(res.doc["lines"]) == len(clean["lines"]) - 1 and not topo.dangling
    pump, hv = by_tag(res.doc, "P-101")[0], by_tag(res.doc, "HV-102")[0]
    assert hv["id"] in topo.neighbours(pump["id"])


def test_add_and_connect_with_refs(clean):
    tank = by_tag(clean, "TK-101")[0]
    res = apply_ops(clean, [
        {"op": "add_entity", "ref": "t", "type": "instrument", "tag": "TT-101", "near": tank["id"], "side": "left"},
        {"op": "connect", "from": tank["id"], "to": "$t"},
    ])
    tt = by_tag(res.doc, "TT-101")[0]
    assert tt["x"] < tank["x"]
    assert tank["id"] in topology.build(res.doc).neighbours(tt["id"])
    others = [entity_bbox(res.doc, e) for e in res.doc["entities"] if e["id"] != tt["id"]]
    box = entity_bbox(res.doc, tt)
    assert not any(box[0] < o[2] and o[0] < box[2] and box[1] < o[3] and o[1] < box[3] for o in others)


def test_title_and_line_number(faulty):
    res = apply_ops(faulty, [{"op": "set_title", "field": "checked_by", "value": "J. Smith"},
                             {"op": "set_line_number", "id": "L19"}])
    assert res.doc["title_block"]["fields"]["CHECKED_BY"]["value"] == "J. Smith"
    assert find_line(res.doc, "L19")["tag"] == "80-RW-1008"


def test_errors_do_not_mutate_input(clean):
    snapshot = repr(clean)
    with pytest.raises(OpError):
        apply_ops(clean, [{"op": "set_tag", "id": "E1", "tag": "TK-9"}, {"op": "move", "id": "NOPE", "dx": 1}])
    assert repr(clean) == snapshot
