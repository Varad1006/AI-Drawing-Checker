"""Offline assistant: a small command grammar that drives the same Workbench tools as the Groq loop.

Used when GROQ_API_KEY is not set, so the chat panel still edits the drawing in demos and tests.
"""
from __future__ import annotations

import re

from ..core.symbols import TYPES, parse_tag
from ..rules.engine import run_rules
from .groq_client import ChatResult
from .tools import Workbench

ENGINE = "offline-parser"

# phrase -> (type, tag prefix)
PHRASES: list[tuple[str, tuple[str, str | None]]] = [
    (r"level transmitter|\blt\b", ("instrument", "LT")), (r"level gauge|level glass|\blg\b", ("instrument", "LG")),
    (r"flow transmitter|\bft\b", ("instrument", "FT")), (r"pressure transmitter|\bpt\b", ("instrument", "PT")),
    (r"pressure gauge|pressure indicator|\bpi\b", ("instrument", "PI")),
    (r"temperature transmitter|\btt\b", ("instrument", "TT")),
    (r"level controller|\blic\b", ("instrument_panel", "LIC")), (r"flow controller|\bfic\b", ("instrument_panel", "FIC")),
    (r"pressure controller|\bpic\b", ("instrument_panel", "PIC")),
    (r"relief valve|safety valve|\bpsv\b", ("relief_valve", "PSV")), (r"check valve|non.?return|\bnrv\b", ("check_valve", "NRV")),
    (r"control valve", ("control_valve", None)), (r"globe valve", ("globe_valve", "HV")), (r"ball valve", ("ball_valve", "HV")),
    (r"gate valve|isolation valve|\bvalve\b", ("gate_valve", "HV")),
    (r"heat exchanger|exchanger", ("heat_exchanger", "E")), (r"pump", ("pump", "P")), (r"tank", ("tank", "TK")),
    (r"vessel|drum", ("vessel", "V")), (r"filter|strainer", ("filter", "FL")),
]
TAG = r"([A-Za-z]{1,4}-?\d{2,4}[A-Za-z]?|[EL]\d+)"
HELP = ("I'm running without an AI key, so I understand commands like:\n"
        "• fix all — apply every automatic fix\n"
        "• rename P-101 to P-102 (or E7 to P-102)\n"
        "• delete HV-104 · move P-102 to 150, 120 · move P-102 up 10 · rotate HV-101 90\n"
        "• add a level transmitter near TK-101 right\n"
        "• add a check valve after P-102 · add a gate valve before P-101\n"
        "• connect LT-101 to TK-101 (with a signal line)\n"
        "• set checked by to J. SMITH · number line L19\n"
        "• check — list the current findings\n"
        "Set GROQ_API_KEY to talk to me in plain English.")


def _kind(text: str) -> tuple[str, str | None] | None:
    for pattern, spec in PHRASES:
        if re.search(pattern, text, re.I):
            return spec
    return None


def _tag_for(wb: Workbench, prefix: str | None, anchor: str | None) -> str | None:
    if not prefix:
        return None
    existing = {e["tag"] for e in wb.doc["entities"] if e.get("tag")}
    number = 101
    if anchor:
        ent = next((e for e in wb.doc["entities"] if e["id"] == anchor or (e.get("tag") or "").upper() == anchor.upper()), None)
        parsed = parse_tag(ent.get("tag")) if ent else None
        number = parsed[1] if parsed else number
    while f"{prefix}-{number}" in existing:
        number += 1
    return f"{prefix}-{number}"


def handle(doc: dict, message: str) -> ChatResult:
    wb = Workbench(doc)
    text = message.strip().rstrip(".!")
    low = text.lower()
    reply = None

    def run(name, **args):
        res = wb.call(name, args)
        if not res.get("ok"):
            raise ValueError(res.get("error"))
        return res

    try:
        if re.fullmatch(r"(help|\?|what can you do)", low):
            reply = HELP
        elif re.search(r"\b(fix|resolve|repair|correct)\b.*\b(all|everything|issues|drawing)\b|^auto.?fix", low):
            run("apply_all_fixes")
            remaining = run_rules(wb.doc)
            reply = (f"Applied {len(wb.messages)} automatic fix step(s). "
                     + (f"{len(remaining)} finding(s) need an engineer's decision: "
                        + "; ".join(f["title"] for f in remaining[:5]) if remaining else "No findings remain."))
        elif re.fullmatch(r"(check|run checks|re-?check|what'?s wrong|list (issues|findings))", low):
            findings = run_rules(wb.doc)
            reply = ("Current findings:\n" + "\n".join(f"• {f['severity']} {f['rule_id']}: {f['title']}" for f in findings)
                     if findings else "The drawing passes every rule.")
        elif m := re.match(rf"(?:rename|retag|change)\s+{TAG}\s+(?:to|as|into)\s+{TAG}$", text, re.I):
            run("set_tag", target=m.group(1), tag=m.group(2).upper())
        elif m := re.match(rf"(?:delete|remove)\s+{TAG}$", text, re.I):
            run("delete", target=m.group(1))
        elif m := re.match(rf"move\s+{TAG}\s+(?:to\s+)?\(?\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)?$", text, re.I):
            run("move_component", target=m.group(1), x=float(m.group(2)), y=float(m.group(3)))
        elif m := re.match(rf"move\s+{TAG}\s+(left|right|up|down)\s+(?:by\s+)?(\d+(?:\.\d+)?)", text, re.I):
            d = float(m.group(3))
            dx, dy = {"left": (-d, 0), "right": (d, 0), "up": (0, d), "down": (0, -d)}[m.group(2).lower()]
            run("move_component", target=m.group(1), dx=dx, dy=dy)
        elif m := re.match(rf"rotate\s+{TAG}\s+(?:by\s+|to\s+)?(-?\d+)", text, re.I):
            run("rotate_component", target=m.group(1), angle=float(m.group(2)))
        elif m := re.match(rf"(?:add|insert|put)\s+(?:an?\s+)?(.+?)\s+(after|before|downstream of|upstream of)\s+{TAG}$", text, re.I):
            spec = _kind(m.group(1))
            if not spec or TYPES[spec[0]]["category"] not in ("valve", "instrument"):
                raise ValueError(f"I can only insert valves or inline instruments into a pipe, not '{m.group(1)}'")
            where = "after" if m.group(2).lower() in ("after", "downstream of") else "before"
            tag = re.search(TAG, m.group(1))
            run("insert_inline", type=spec[0], tag=tag.group(1).upper() if tag else _tag_for(wb, spec[1], m.group(3)),
                **{where: m.group(3)})
        elif m := re.match(rf"(?:add|place|put)\s+(?:an?\s+)?(.+?)\s+(?:near|next to|beside|by)\s+{TAG}(?:\s+(?:on the\s+)?(left|right|above|below))?$", text, re.I):
            spec = _kind(m.group(1))
            if not spec:
                raise ValueError(f"I don't know the symbol '{m.group(1)}'")
            tag = re.search(TAG, m.group(1))
            run("add_component", type=spec[0], near=m.group(2), side=(m.group(3) or "right").lower(),
                tag=tag.group(1).upper() if tag else _tag_for(wb, spec[1], m.group(2)))
            if TYPES[spec[0]]["category"] == "instrument" and spec[0] == "instrument":
                new_id = sorted(wb.changed, key=lambda s: int(s[1:]) if s[1:].isdigit() else 0)[-1]
                run("connect", from_component=m.group(2), to_component=new_id, kind="process")
        elif m := re.match(rf"connect\s+{TAG}\s+(?:to|and|with)\s+{TAG}(?:\s+with\s+an?\s+(signal|process)\s+line)?$", text, re.I):
            run("connect", from_component=m.group(1), to_component=m.group(2), kind=(m.group(3) or "process").lower())
        elif m := re.match(r"set\s+(?:the\s+)?(title|dwg no|drawing number|rev|revision|drawn by|checked by|date)\s+(?:to|=|as)\s+(.+)$", text, re.I):
            field = {"title": "TITLE", "dwg no": "DWG_NO", "drawing number": "DWG_NO", "rev": "REV", "revision": "REV",
                     "drawn by": "DRAWN_BY", "checked by": "CHECKED_BY", "date": "DATE"}[m.group(1).lower()]
            run("set_title_block", field=field, value=m.group(2).strip().upper() if field != "DATE" else m.group(2).strip())
        elif m := re.match(rf"number\s+(?:line\s+)?{TAG}(?:\s+(?:as|to)\s+(\S+))?$", text, re.I):
            run("set_line_number", line=m.group(1), number=m.group(2))
        else:
            reply = "I didn't understand that. " + HELP
    except ValueError as exc:
        reply = f"I couldn't do that: {exc}"

    if reply is None:
        reply = "Done — " + "; ".join(wb.messages) + "."
    return ChatResult(reply=reply, workbench=wb, engine=ENGINE)
