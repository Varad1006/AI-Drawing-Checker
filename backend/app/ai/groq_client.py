"""Groq-powered AI review and chat-driven editing.

* review(): asks the model for engineering findings the deterministic rules did not already report.
  Findings are labelled source="ai" with the model's confidence; nothing is simulated.
* chat(): a tool-calling loop. The model edits the drawing only through Workbench tools, so every AI
  change is a normal edit operation stored in the revision history.

Everything here is optional: without GROQ_API_KEY the app runs on the rule engine and the offline
command parser.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field

from .. import config
from ..core import geometry as g
from ..core.document import entity_bbox, find_entity, find_line
from .tools import TOOLS, Workbench, describe_drawing

try:
    from groq import Groq
    import groq as groq_sdk
except ImportError:  # pragma: no cover
    Groq = None
    groq_sdk = None

logger = logging.getLogger(__name__)
MAX_STEPS = 8


class AIError(RuntimeError):
    pass


def enabled() -> bool:
    return bool(config.GROQ_API_KEY) and Groq is not None


def _client():
    if not enabled():
        raise AIError("Groq is not configured (set GROQ_API_KEY)")
    return Groq(api_key=config.GROQ_API_KEY, timeout=90, max_retries=2)


def _friendly(exc: Exception) -> str:
    if groq_sdk is not None:
        if isinstance(exc, groq_sdk.AuthenticationError):
            return "Groq rejected the API key (check GROQ_API_KEY)."
        if isinstance(exc, groq_sdk.RateLimitError):
            return "Groq rate limit reached — wait a moment and try again."
        if isinstance(exc, groq_sdk.APIConnectionError):
            return "Could not reach the Groq API."
        if isinstance(exc, groq_sdk.APIStatusError):
            return f"Groq API error {exc.status_code}: {getattr(exc, 'message', exc)}"
    return f"AI request failed: {exc}"


def _complete(**kwargs):
    try:
        resp = _client().chat.completions.create(model=config.GROQ_MODEL, **kwargs)
        if getattr(resp, "usage", None):
            logger.info("groq %s: %s prompt + %s completion tokens", config.GROQ_MODEL, resp.usage.prompt_tokens,
                        resp.usage.completion_tokens)
        return resp
    except AIError:
        raise
    except Exception as exc:
        logger.warning("Groq call failed: %s", exc)
        raise AIError(_friendly(exc)) from exc


# ---------------------------------------------------------------------------------------------------
# AI review
# ---------------------------------------------------------------------------------------------------

REVIEW_SYSTEM = """You are a senior lead engineer checking a P&ID (piping and instrumentation diagram) before issue.
You receive the drawing as structured data extracted from CAD, plus the findings a deterministic rule engine already
raised. Report ONLY additional, concrete problems that a lead checker would mark up and that you can justify from the
data — for example: control loops missing indicators or alarms, vessels/tanks without vents or drains, filters without
differential-pressure measurement, pumps without discharge pressure indication, instruments without isolation,
inconsistent line service codes or sizes along a run, missing minimum-flow protection, spec breaks.

The rule engine already covers these categories completely — never report anything in them: tag uniqueness and
format, tag/symbol mismatch, untagged items, unconnected equipment, open pipe ends, pump check and isolation valves,
tank/vessel level instruments, PSVs on pressure vessels, control-valve loops, line numbers, title block, overlaps.
A pipe run keeps one line number across valves, so pipe pieces without their own number are normal.

Do not invent components that are not in the data. In prose, refer to components by tag; if a tag is duplicated,
name them by role (e.g. "the standby pump P-101"). Suggest ISA-5.1 tags using the loop number of the equipment
served (e.g. PI-101, PDIT-101).
Respond with JSON only: {"findings": [{"title": str, "description": str, "recommendation": str,
"severity": "LOW"|"MEDIUM"|"HIGH"|"CRITICAL", "category": str, "confidence": number 0-1,
"entities": [component ids like "E4"], "lines": [pipe ids like "L7"]}]}. Return at most 8 findings; return
{"findings": []} if there is nothing solid."""


def _resolve_refs(doc: dict, refs) -> list[str]:
    out = []
    for r in refs or []:
        r = str(r).strip()
        if find_entity(doc, r):
            out.append(r)
            continue
        hits = [e["id"] for e in doc["entities"] if (e.get("tag") or "").upper() == r.upper()]
        if len(hits) == 1:
            out.append(hits[0])
    return list(dict.fromkeys(out))


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise AIError("the model did not return JSON")
    return json.loads(m.group(0))


def review(doc: dict, rule_findings: list[dict]) -> list[dict]:
    known = "\n".join(f"- {f['rule_id']}: {f['title']}" for f in rule_findings) or "- none"
    messages = [
        {"role": "system", "content": REVIEW_SYSTEM},
        {"role": "user", "content": f"DRAWING\n{describe_drawing(doc, rule_findings)}\n\nRULE ENGINE FINDINGS "
                                    f"(already reported, do not repeat)\n{known}"},
    ]
    try:
        resp = _complete(messages=messages, temperature=0.2, response_format={"type": "json_object"})
    except AIError as exc:
        if "response_format" not in str(exc):
            raise
        resp = _complete(messages=messages, temperature=0.2)
    data = _parse_json(resp.choices[0].message.content)
    findings = []
    for i, f in enumerate((data.get("findings") or [])[:8], 1):
        if not isinstance(f, dict) or not f.get("title"):
            continue
        ents = _resolve_refs(doc, f.get("entities"))
        lines = [ln for ln in dict.fromkeys(str(x).strip() for x in f.get("lines") or []) if find_line(doc, ln)]
        if not ents and not lines:
            continue  # a finding we cannot place on the drawing is not actionable
        box = None
        for eid in ents:
            box = g.bbox_union(box, entity_bbox(doc, find_entity(doc, eid)))
        for lid in lines:
            box = g.bbox_union(box, g.bbox_of_points(find_line(doc, lid)["pts"]))
        severity = str(f.get("severity", "MEDIUM")).upper()
        severity = severity if severity in ("LOW", "MEDIUM", "HIGH", "CRITICAL") else "MEDIUM"
        digest = hashlib.sha1((f["title"].lower() + "|" + ",".join(sorted(ents + lines))).encode()).hexdigest()[:10]
        try:
            confidence = max(0.0, min(1.0, float(f.get("confidence", 0.7))))
        except (TypeError, ValueError):
            confidence = 0.7
        findings.append({
            "key": f"AI:{digest}", "rule_id": f"AI-{i:02d}", "source": "ai",
            "category": str(f.get("category") or "AI review")[:40], "severity": severity,
            "title": str(f["title"])[:160], "description": str(f.get("description", ""))[:1200],
            "recommendation": str(f.get("recommendation", ""))[:800], "confidence": round(confidence, 2),
            "entities": ents, "lines": lines, "bbox": box, "location": g.bbox_center(box) if box else None, "fix": None,
        })
    return findings


# ---------------------------------------------------------------------------------------------------
# chat-driven editing
# ---------------------------------------------------------------------------------------------------

CHAT_SYSTEM = """You are Lead Checker, an AI assistant inside a P&ID review tool. The engineer talks to you about the
drawing below and asks you to explain findings or change the drawing.

How to work:
- Make every change with the tools. Never claim a change you did not make with a tool call.
- Refer to components by id (E7) when a tag is duplicated; otherwise tags are fine.
- Coordinates are drawing units, y axis up. Place new symbols with `near` + `side` so they land in a clear spot,
  then `connect` them (process for pipes/nozzles, signal for instrument loops).
- Valves go into existing pipes with insert_inline (after/before a component).
- Follow ISA-5.1 tags: P- pump, TK- tank, V- vessel, HV- manual valve, NRV- check valve, FV/LV/PV/TV- control valve,
  PSV- relief valve, instruments like FT/LT/PT/TT (transmitters), FIC/LIC (controllers), PI/LG (local indicators).
  Reuse the loop number of the equipment or valve the instrument serves.
- Work in as few steps as possible: put every edit for the request into ONE step as several tool calls. Calls in a
  step run in order, so a component added earlier in the step can be referenced by its tag later in the same step
  (or use add_component's connect_to). Call run_checks once at the end, not after every edit.
- Reply in a few short sentences or bullets: what you changed (with tags) and what remains. Do not repeat the
  whole drawing. If the request is a question, answer it from the data without editing.

CURRENT DRAWING
"""


@dataclass
class ChatResult:
    reply: str
    workbench: Workbench
    engine: str
    tool_calls: list[dict] = field(default_factory=list)


def chat(doc: dict, history: list[dict], message: str) -> ChatResult:
    wb = Workbench(doc)
    msgs = [{"role": "system", "content": CHAT_SYSTEM + describe_drawing(doc)}]
    msgs += [{"role": m["role"], "content": m["content"]} for m in history[-12:] if m["role"] in ("user", "assistant")]
    msgs.append({"role": "user", "content": message})
    calls: list[dict] = []
    reply = None
    extra = {"reasoning_effort": "low"} if config.GROQ_MODEL.startswith("openai/gpt-oss") else {}
    for _ in range(MAX_STEPS):
        try:
            resp = _complete(messages=msgs, tools=TOOLS, tool_choice="auto", temperature=0.2,
                             max_completion_tokens=2048, **extra)
        except AIError as exc:
            if not wb.messages:
                raise
            reply = _summary(wb, f"I had to stop early ({exc}), but these edits are saved:")
            break
        m = resp.choices[0].message
        if not m.tool_calls:
            reply = (m.content or "").strip()
            break
        msgs.append({"role": "assistant", "content": m.content or "", "tool_calls": [
            {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in m.tool_calls]})
        for tc in m.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = None
            result = wb.call(tc.function.name, args) if isinstance(args, dict) else {"ok": False, "error": "arguments were not valid JSON"}
            calls.append({"tool": tc.function.name, "args": args, "ok": result.get("ok", False)})
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)[:8000]})
    if reply is None:
        reply = _summary(wb, "Here is what I changed:") if wb.messages else "I could not complete that request."
    elif not reply:
        reply = _summary(wb, "Done:") if wb.messages else "Done."
    return ChatResult(reply=reply, workbench=wb, engine=f"groq:{config.GROQ_MODEL}", tool_calls=calls)


def _summary(wb: Workbench, lead: str) -> str:
    """Deterministic wrap-up when the model runs out of steps or budget after making edits."""
    from ..rules.engine import run_rules
    remaining = run_rules(wb.doc)
    lines = [lead] + [f"- {m}" for m in wb.messages]
    lines.append(f"{len(remaining)} rule finding(s) remain." if remaining else "No rule findings remain.")
    return "\n".join(lines)
