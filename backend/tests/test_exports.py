import io

import ezdxf

from app.exporters.dxf_writer import dxf_bytes
from app.exporters.pdf_report import report_pdf
from app.parsers.dxf_parser import parse_dxf
from app.rules.engine import run_rules
from app.services import autofix_doc


def test_corrected_dxf_reimports_with_fixes(tmp_path, faulty):
    fixed, *_ = autofix_doc(faulty)
    (tmp_path / "fixed.dxf").write_bytes(dxf_bytes(fixed))
    back = parse_dxf(str(tmp_path / "fixed.dxf"))
    assert sorted(f["rule_id"] for f in run_rules(back)) == ["R011", "R014"]


def test_markup_dxf_has_checker_layer(faulty):
    issues = run_rules(faulty)
    dxf = ezdxf.read(io.StringIO(dxf_bytes(faulty, issues).decode()))
    checker = dxf.modelspace().query('*[layer=="CHECKER"]')
    clouds = [e for e in checker if e.dxftype() == "LWPOLYLINE"]
    assert len(clouds) == len(issues)
    assert all(b > 0 for c in clouds for *_, b in c.get_points("xyb"))


def test_report_pdf(faulty):
    issues = [{**f, "status": "OPEN", "comment": ""} for f in run_rules(faulty)]
    pdf = report_pdf(faulty, issues, {"filename": "x.dxf", "revision": 1, "revisions": 1, "stats": {"open": 9}})
    assert pdf.startswith(b"%PDF") and len(pdf) > 5000
