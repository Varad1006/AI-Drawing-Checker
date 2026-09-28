from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from app.config import SAMPLES_DIR
from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def demo(client):
    return client.post("/api/drawings/demo").json()


def test_health_and_rules(client):
    assert client.get("/api/health").json()["ai"]["enabled"] is False
    body = client.get("/api/rules").json()
    assert len(body["rules"]) == 15 and any(t["type"] == "pump" for t in body["types"])


def test_upload_validation(client):
    assert client.post("/api/drawings/upload", files={"file": ("a.txt", b"x")}).status_code == 415
    r = client.post("/api/drawings/upload", files={"file": ("a.dxf", b"garbage")})
    assert r.status_code == 422 and "DXF" in r.json()["detail"]


def test_upload_pdf(client):
    with open(SAMPLES_DIR / "water_treatment_pid.pdf", "rb") as f:
        d = client.post("/api/drawings/upload", files={"file": ("sheet.pdf", f, "application/pdf")}).json()
    assert d["format"] == "pdf" and d["stats"]["open"] == 6


def test_full_check_workflow(client, demo):
    did = demo["id"]
    assert demo["stats"]["open"] == 9 and demo["stats"]["fixable"] == 7
    detail = client.get(f"/api/drawings/{did}").json()
    assert detail["document"]["entities"] and detail["topology"]["attachments"]

    dup = next(i for i in detail["issues"] if i["rule_id"] == "R001")
    r = client.post(f"/api/drawings/{did}/issues/{quote(dup['key'], safe='')}/fix").json()
    assert r["drawing"]["head_rev"] == 2 and r["drawing"]["stats"]["fixed"] == 1
    assert any(i["key"] == dup["key"] and i["status"] == "FIXED" for i in r["issues"])

    r = client.post(f"/api/drawings/{did}/autofix").json()
    assert r["drawing"]["stats"]["open"] == 2 and r["revisions"][-1]["author"] == "auto-fix"

    loop = next(i for i in r["issues"] if i["rule_id"] == "R011")
    r = client.put(f"/api/drawings/{did}/issues/{quote(loop['key'], safe='')}/review",
                   json={"status": "REJECTED", "comment": "Loop shown on WT-I-004"}).json()
    assert r["drawing"]["stats"]["rejected"] == 1
    assert next(i for i in r["issues"] if i["key"] == loop["key"])["comment"] == "Loop shown on WT-I-004"

    r = client.post(f"/api/drawings/{did}/head", json={"rev_no": 1}).json()
    assert r["drawing"]["head_rev"] == 1 and r["drawing"]["stats"]["open"] == 8
    r = client.post(f"/api/drawings/{did}/edits", json={"ops": [{"op": "move", "id": "E1", "dx": 5, "dy": 0}]}).json()
    assert r["drawing"]["head_rev"] == 2 and r["drawing"]["max_rev"] == 2, "editing after undo drops the redo branch"
    assert r["drawing"]["stats"]["open"] == 8, "findings are recomputed for the new revision, not served from cache"
    r = client.post(f"/api/drawings/{did}/autofix").json()
    assert r["drawing"]["stats"]["open"] == 1 and r["drawing"]["stats"]["fixed"] == 7
    assert client.post(f"/api/drawings/{did}/edits", json={"ops": [{"op": "move", "id": "E999", "dx": 1}]}).status_code == 400


def test_offline_chat_edits_drawing(client, demo):
    did = demo["id"]
    r = client.post(f"/api/drawings/{did}/chat", json={"message": "add a check valve after E7"}).json()
    last = r["chat"][-1]
    assert last["engine"] == "offline-parser" and last["rev_no"] == 2 and "check valve" in last["actions"][0]
    r = client.post(f"/api/drawings/{did}/chat", json={"message": "set checked by to j. smith"}).json()
    assert r["document"]["title_block"]["fields"]["CHECKED_BY"]["value"] == "J. SMITH"
    r = client.post(f"/api/drawings/{did}/chat", json={"message": "rename P-101 to P-105"}).json()
    assert "used by 2 components" in r["chat"][-1]["content"] and r["drawing"]["head_rev"] == 3
    r = client.post(f"/api/drawings/{did}/chat", json={"message": "fix all"}).json()
    assert r["drawing"]["stats"]["open"] == 1  # only the control-loop finding needs an engineer
    assert len(client.get(f"/api/drawings/{did}/chat").json()) == 8


def test_exports_and_delete(client, demo):
    did = demo["id"]
    for kind, magic in (("dxf", b"  0\nSECTION"), ("markup-dxf", b"  0\nSECTION"), ("report-pdf", b"%PDF"), ("original", b"")):
        r = client.get(f"/api/drawings/{did}/export/{kind}")
        assert r.status_code == 200 and r.content.startswith(magic)
    assert client.get(f"/api/drawings/{did}/export/zip").status_code == 404
    assert client.post(f"/api/drawings/{did}/ai-review").status_code == 409
    assert client.delete(f"/api/drawings/{did}").status_code == 204
    assert client.get(f"/api/drawings/{did}").status_code == 404
