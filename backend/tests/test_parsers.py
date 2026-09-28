import ezdxf
import pytest

from app.config import SAMPLES_DIR
from app.core import topology
from app.exporters.dxf_writer import build_dxf
from app.exporters.pdf_report import drawing_pdf
from app.parsers.dxf_parser import ParseError, parse_dxf
from app.parsers.pdf_parser import parse_pdf
from app.rules.engine import run_rules


def signature(doc):
    return (sorted((e["type"], e.get("tag") or "") for e in doc["entities"]),
            sorted(ln.get("tag") or "" for ln in doc["lines"]),
            sorted(f["key"].split(":")[0] for f in run_rules(doc)))


@pytest.mark.parametrize("errors", [True, False])
def test_dxf_round_trip_is_lossless(tmp_path, errors):
    from app.samples import water_treatment
    doc = water_treatment(errors)
    build_dxf(doc).saveas(tmp_path / "rt.dxf")
    back = parse_dxf(str(tmp_path / "rt.dxf"))
    assert signature(back) == signature(doc)
    assert back["title_block"]["fields"]["DWG_NO"]["value"] == "WT-P-001"
    assert back["source"]["units"] == "mm"


def test_committed_samples_parse():
    doc = parse_dxf(str(SAMPLES_DIR / "water_treatment_pid.dxf"))
    assert len(run_rules(doc)) == 9
    assert run_rules(parse_dxf(str(SAMPLES_DIR / "water_treatment_pid_clean.dxf"))) == []


def test_foreign_style_dxf(tmp_path):
    """Differently named blocks, tags as loose TEXT, split instrument bubble, LINE pieces, dashed signal."""
    dxf = ezdxf.new(setup=True)
    pump = dxf.blocks.new("CENTRIFUGAL_PUMP")
    pump.add_circle((0, 0), 5)
    valve = dxf.blocks.new("VALVE-GATE")
    valve.add_lwpolyline([(-4, 2.5), (-4, -2.5), (4, 2.5), (4, -2.5)], close=True)
    bubble = dxf.blocks.new("ISA_INSTR_BUBBLE")
    bubble.add_circle((0, 0), 4)
    msp = dxf.modelspace()
    msp.add_blockref("CENTRIFUGAL_PUMP", (0, 0))
    msp.add_text("P-201", height=2).set_placement((0, -9), align=ezdxf.enums.TextEntityAlignment.CENTER)
    msp.add_blockref("VALVE-GATE", (40, 0))
    msp.add_text("HV-201", height=2).set_placement((40, 5), align=ezdxf.enums.TextEntityAlignment.CENTER)
    msp.add_blockref("ISA_INSTR_BUBBLE", (40, 25))
    msp.add_text("PT", height=1.8).set_placement((40, 0.5 + 25), align=ezdxf.enums.TextEntityAlignment.BOTTOM_CENTER)
    msp.add_text("201", height=1.8).set_placement((40, -0.5 + 25), align=ezdxf.enums.TextEntityAlignment.TOP_CENTER)
    msp.add_line((5, 0), (20, 0), dxfattribs={"layer": "PROCESS"})
    msp.add_line((20, 0), (36, 0), dxfattribs={"layer": "PROCESS"})
    msp.add_text("50-CW-2001", height=2).set_placement((12, 1.2))
    msp.add_line((40, 21), (40, 11), dxfattribs={"layer": "INSTR_SIGNAL"})
    msp.add_lwpolyline([(70, -10), (90, -10), (90, 10), (70, 10)], close=True)
    msp.add_text("TK-201", height=2).set_placement((80, 0), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
    dxf.saveas(tmp_path / "foreign.dxf")

    doc = parse_dxf(str(tmp_path / "foreign.dxf"))
    tags = {e.get("tag"): e for e in doc["entities"]}
    assert tags["P-201"]["type"] == "pump" and tags["HV-201"]["type"] == "gate_valve"
    assert tags["PT-201"]["type"] == "instrument" and tags["PT-201"]["label"]["style"] == "split"
    assert tags["TK-201"]["block"] is None and tags["TK-201"]["type"] == "tank"
    process = [ln for ln in doc["lines"] if ln["kind"] == "process"]
    assert len(process) == 1 and process[0]["tag"] == "50-CW-2001", "LINE pieces merged and numbered"
    assert [ln["kind"] for ln in doc["lines"]].count("signal") == 1
    topo = topology.build(doc)
    assert tags["HV-201"]["id"] in topo.neighbours(tags["P-201"]["id"])


def test_bad_files(tmp_path):
    (tmp_path / "junk.dxf").write_text("hello")
    with pytest.raises(ParseError):
        parse_dxf(str(tmp_path / "junk.dxf"))
    (tmp_path / "junk.pdf").write_bytes(b"%PDF-nope")
    with pytest.raises(ParseError):
        parse_pdf(str(tmp_path / "junk.pdf"))


def test_vector_pdf(tmp_path, faulty):
    (tmp_path / "s.pdf").write_bytes(drawing_pdf(faulty))
    doc = parse_pdf(str(tmp_path / "s.pdf"))
    tags = {e["tag"] for e in doc["entities"]}
    assert {"P-101", "TK-101", "FT-101", "FIC-101", "LV-102", "pt102"} <= tags
    assert doc["meta"]["connectivity"] is False
    assert doc["title_block"]["fields"]["CHECKED_BY"]["value"] == ""
    assert sorted(f["rule_id"] for f in run_rules(doc)) == ["R001", "R002", "R009", "R010", "R011", "R014"]
