"""The Groq integration, driven by a scripted fake model (no network)."""
import json
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from app.ai import groq_client
from app.main import app


def reply(content=None, calls=()):
    tool_calls = [NS(id=f"call{i}", function=NS(name=name, arguments=json.dumps(args))) for i, (name, args) in enumerate(calls)]
    return NS(choices=[NS(message=NS(content=content, tool_calls=tool_calls or None))])


@pytest.fixture
def fake_groq(monkeypatch):
    script: list = []
    seen: list = []

    def complete(**kwargs):
        seen.append(kwargs)
        return script.pop(0)

    monkeypatch.setattr(groq_client, "enabled", lambda: True)
    monkeypatch.setattr(groq_client, "_complete", complete)
    return script, seen


def test_chat_tool_loop(fake_groq, faulty):
    script, seen = fake_groq
    script += [
        reply(calls=[("set_tag", {"target": "E7", "tag": "P-102"}),
                     ("insert_inline", {"type": "check_valve", "after": "P-102"})]),
        reply(calls=[("run_checks", {}), ("delete", {"target": "NOPE"})]),
        reply("Renumbered the standby pump to P-102 and added NRV-102 on its discharge."),
    ]
    result = groq_client.chat(faulty, [], "fix the standby pump")
    wb = result.workbench
    assert [op["op"] for op in wb.ops] == ["set_tag", "insert_inline"]
    assert any("NRV-102" in m for m in wb.messages)
    assert [c["ok"] for c in result.tool_calls] == [True, True, True, False]
    assert "P-102" in result.reply
    tool_msgs = [m for m in seen[-1]["messages"] if m["role"] == "tool"]
    assert json.loads(tool_msgs[-1]["content"])["ok"] is False, "tool errors are fed back to the model"
    assert seen[0]["tools"] and "CURRENT DRAWING" in seen[0]["messages"][0]["content"]


def test_review_maps_tags_and_labels_source(fake_groq, faulty):
    script, _ = fake_groq
    script.append(reply(json.dumps({"findings": [
        {"title": "Filter has no differential pressure measurement", "description": "FL-101 fouling is invisible.",
         "recommendation": "Add PDIT-101 across FL-101.", "severity": "medium", "category": "Instrumentation",
         "confidence": 0.8, "entities": ["FL-101", "E999"]}]})))
    findings = groq_client.review(faulty, [])
    assert len(findings) == 1
    f = findings[0]
    assert f["source"] == "ai" and f["severity"] == "MEDIUM" and f["key"].startswith("AI:")
    assert len(f["entities"]) == 1 and f["bbox"]


def test_api_uses_groq_when_enabled(fake_groq):
    script, _ = fake_groq
    with TestClient(app) as c:
        script.append(reply(json.dumps({"findings": [
            {"title": "Pump discharge has no pressure gauge", "description": "d", "recommendation": "r",
             "severity": "LOW", "confidence": 0.7, "entities": ["HV-102"]}]})))
        d = c.post("/api/drawings/demo").json()  # upload triggers the background AI review
        detail = c.get(f"/api/drawings/{d['id']}").json()
        assert detail["drawing"]["ai_status"] == "done"
        ai = [i for i in detail["issues"] if i["source"] == "ai"]
        assert len(ai) == 1 and ai[0]["status"] == "OPEN"

        script += [reply(calls=[("set_title_block", {"field": "CHECKED_BY", "value": "LEAD AI"})]), reply("Signed it.")]
        r = c.post(f"/api/drawings/{d['id']}/chat", json={"message": "sign the title block"}).json()
        assert r["revisions"][-1]["author"] == "ai" and r["chat"][-1]["engine"].startswith("groq:")

        def boom(**_):
            raise groq_client.AIError("Groq rate limit reached — wait a moment and try again.")
        groq_client._complete = boom  # restored by monkeypatch at teardown
        r = c.post(f"/api/drawings/{d['id']}/chat", json={"message": "hello"}).json()
        assert "rate limit" in r["chat"][-1]["content"] and r["drawing"]["head_rev"] == 2


def test_rate_limit_mid_loop_keeps_completed_edits(fake_groq, faulty):
    script, _ = fake_groq
    script.append(reply(calls=[("set_tag", {"target": "E7", "tag": "P-102"})]))

    def later(**_):
        raise groq_client.AIError("Groq rate limit reached — wait a moment and try again.")

    first = groq_client._complete

    def complete(**kw):
        return first(**kw) if script else later(**kw)

    groq_client._complete = complete
    result = groq_client.chat(faulty, [], "renumber the standby pump")
    assert [op["op"] for op in result.workbench.ops] == ["set_tag"]
    assert "rate limit" in result.reply and "Retagged" in result.reply and "remain" in result.reply


def test_step_cap_summarises_instead_of_failing(fake_groq, faulty, monkeypatch):
    script, _ = fake_groq
    monkeypatch.setattr(groq_client, "MAX_STEPS", 2)
    script += [reply(calls=[("set_title_block", {"field": "CHECKED_BY", "value": "A"})]),
               reply(calls=[("run_checks", {})])]
    result = groq_client.chat(faulty, [], "sign it")
    assert result.reply.startswith("Here is what I changed:") and "CHECKED_BY" in result.reply


def test_add_component_can_connect_in_one_call(faulty):
    from app.ai.tools import Workbench
    from app.core import topology
    wb = Workbench(faulty)
    res = wb.call("add_component", {"type": "instrument", "tag": "LIC-102", "near": "LV-102", "side": "above",
                                    "connect_to": "LV-102", "connect_kind": "signal"})
    assert res["ok"], res
    lic = next(e for e in wb.doc["entities"] if e["tag"] == "LIC-102")
    assert lic["type"] == "instrument_panel", "controller type follows the ISA tag"
    lv = next(e for e in wb.doc["entities"] if e["tag"] == "LV-102")
    assert lv["id"] in topology.build(wb.doc).neighbours(lic["id"])


def test_review_places_pipe_findings_and_drops_unplaceable(fake_groq, faulty):
    script, _ = fake_groq
    script.append(reply(json.dumps({"findings": [
        {"title": "Line service code changes mid-run", "severity": "LOW", "entities": [], "lines": ["L16"]},
        {"title": "Vague concern", "severity": "LOW", "entities": [], "lines": []}]})))
    findings = groq_client.review(faulty, [])
    assert len(findings) == 1 and findings[0]["lines"] == ["L16"] and findings[0]["bbox"]


def test_tools_warn_about_tag_convention(faulty):
    from app.ai.tools import Workbench
    wb = Workbench(faulty)
    res = wb.call("insert_inline", {"type": "check_valve", "tag": "CV-102", "after": "E7"})
    assert res["ok"] and "NRV" in res["warnings"][0]
