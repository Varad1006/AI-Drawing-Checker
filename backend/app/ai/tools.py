"""The assistant's toolset: a Workbench that applies edit operations to a working copy of the drawing.

Both the Groq tool-calling loop and the offline command parser drive the same Workbench, so every
change the assistant makes is an ordinary, replayable edit operation.
"""
from __future__ import annotations

from ..core import topology
from ..core.document import describe
from ..core.ops import OpError, apply_ops
from ..core.symbols import TITLE_FIELDS, TYPES
from ..rules.engine import run_rules

COMPONENT_TYPES = list(TYPES)
INLINE_TYPES = [t for t, m in TYPES.items() if m["category"] in ("valve", "instrument")]


class Workbench:
    def __init__(self, doc: dict):
        self.doc = doc
        self.ops: list[dict] = []
        self.messages: list[str] = []
        self.changed: set[str] = set()
        self.refs: dict[str, str] = {}

    def _apply(self, ops: list[dict]) -> dict:
        res = apply_ops(self.doc, ops, refs=self.refs)
        self.doc = res.doc
        self.refs.update(res.refs)
        self.ops += ops
        self.messages += res.messages
        self.changed |= res.changed
        return {"ok": True, "done": res.messages, "changed_ids": sorted(res.changed)}

    def call(self, name: str, args: dict) -> dict:
        fn = getattr(self, f"t_{name}", None)
        if fn is None:
            return {"ok": False, "error": f"unknown tool {name}"}
        try:
            return fn(**(args or {}))
        except OpError as exc:
            return {"ok": False, "error": str(exc)}
        except TypeError as exc:
            return {"ok": False, "error": f"bad arguments: {exc}"}

    # ---- read-only -----------------------------------------------------------------------------------

    def t_get_drawing(self) -> dict:
        return {"ok": True, "drawing": describe_drawing(self.doc)}

    def t_run_checks(self) -> dict:
        findings = run_rules(self.doc)
        return {"ok": True, "count": len(findings), "findings": [
            {"key": f["key"], "severity": f["severity"], "rule": f["rule_id"], "title": f["title"],
             "fix": f["fix"]["label"] if f.get("fix") else None} for f in findings]}

    # ---- edits ---------------------------------------------------------------------------------------

    def t_move_component(self, target: str, x: float | None = None, y: float | None = None,
                         dx: float | None = None, dy: float | None = None) -> dict:
        op = {"op": "move", "id": target}
        if x is not None and y is not None:
            op.update(x=x, y=y)
        else:
            op.update(dx=dx or 0, dy=dy or 0)
        return self._apply([op])

    def t_rotate_component(self, target: str, angle: float) -> dict:
        return self._apply([{"op": "rotate", "id": target, "angle": angle}])

    def t_set_tag(self, target: str, tag: str) -> dict:
        return self._apply([{"op": "set_tag", "id": target, "tag": tag}])

    def t_delete(self, target: str, remove_dead_end_pipes: bool = True) -> dict:
        return self._apply([{"op": "delete", "id": target, "cascade": remove_dead_end_pipes}])

    def t_add_component(self, type: str, tag: str | None = None, x: float | None = None, y: float | None = None,
                        near: str | None = None, side: str = "right", distance: float | None = None) -> dict:
        op = {"op": "add_entity", "type": type, "tag": tag, "side": side}
        if x is not None and y is not None:
            op.update(x=x, y=y)
        if near:
            op["near"] = near
        if distance is not None:
            op["distance"] = distance
        return self._apply([op])

    def t_connect(self, from_component: str, to_component: str, kind: str = "process",
                  line_number: str | None = None) -> dict:
        return self._apply([{"op": "connect", "from": from_component, "to": to_component, "kind": kind,
                             "tag": line_number}])

    def t_insert_inline(self, type: str, tag: str | None = None, after: str | None = None, before: str | None = None,
                        line: str | None = None) -> dict:
        op = {"op": "insert_inline", "type": type, "tag": tag}
        for k, v in (("after", after), ("before", before), ("line", line)):
            if v:
                op[k] = v
        return self._apply([op])

    def t_extend_pipe(self, line: str, end: str, to_component: str) -> dict:
        return self._apply([{"op": "extend_line", "id": line, "end": end, "to": to_component}])

    def t_set_line_number(self, line: str, number: str | None = None) -> dict:
        return self._apply([{"op": "set_line_number", "id": line, "tag": number}])

    def t_set_title_block(self, field: str, value: str) -> dict:
        return self._apply([{"op": "set_title", "field": field, "value": value}])

    def t_apply_fix(self, issue_key: str) -> dict:
        finding = next((f for f in run_rules(self.doc) if f["key"] == issue_key), None)
        if finding is None:
            return {"ok": False, "error": "no current finding has that key — call run_checks for fresh keys"}
        if not finding.get("fix"):
            return {"ok": False, "error": "that finding has no automatic fix; make the edit with the other tools"}
        return self._apply(finding["fix"]["ops"])

    def t_apply_all_fixes(self) -> dict:
        from ..services import autofix_doc
        doc, ops, messages, changed = autofix_doc(self.doc)
        self.doc = doc
        self.ops += ops
        self.messages += messages
        self.changed |= changed
        return {"ok": True, "done": messages or ["nothing to fix automatically"], "changed_ids": sorted(changed)}


# ---------------------------------------------------------------------------------------------------
# drawing description for the model
# ---------------------------------------------------------------------------------------------------

def describe_drawing(doc: dict, findings: list[dict] | None = None) -> str:
    topo = topology.build(doc)
    by_id = {e["id"]: e for e in doc["entities"]}
    b = doc["bounds"]
    name = lambda node: (by_id[node].get("tag") or node) if node in by_id else ("junction" if node.startswith("J") else "OPEN END")  # noqa: E731
    out = [
        f"Units: {doc['source'].get('units', 'mm')}, y axis points up. Extents x {b[0]:.0f}..{b[2]:.0f}, y {b[1]:.0f}..{b[3]:.0f}.",
        f"Source format: {doc['source']['format'].upper()}. Connectivity analysis: "
        f"{'available' if doc.get('meta', {}).get('connectivity', True) else 'unavailable (PDF)'}.",
        "",
        "COMPONENTS (id | type | tag | centre | rotation | directly connected to):",
    ]
    for e in doc["entities"]:
        near = sorted(name(n) for n in topo.neighbours(e["id"]))
        out.append(f"{e['id']} | {e['type']} | {e.get('tag') or '-'} | ({e['x']:.1f}, {e['y']:.1f}) | "
                   f"{e.get('rot', 0):.0f}° | {', '.join(near) or 'nothing'}")
    out += ["", "PIPES (id | kind | line number | from -> to [in flow order] | points):"]
    for ln in doc["lines"]:
        chain = topo.chain.get(ln["id"], [])
        route = " -> ".join(name(n) for n in chain) if chain else "?"
        pts = " ".join(f"({p[0]:.0f},{p[1]:.0f})" for p in ln["pts"])
        out.append(f"{ln['id']} | {ln.get('kind', 'process')} | {ln.get('tag') or '-'} | {route} | {pts}")
    tb = doc.get("title_block")
    out += ["", "TITLE BLOCK: " + (", ".join(f"{k}={v.get('value') or '(blank)'}" for k, v in tb["fields"].items())
                                   if tb else "none")]
    findings = run_rules(doc) if findings is None else findings
    out += ["", "OPEN FINDINGS (key | severity | rule | title | automatic fix):"]
    for f in findings:
        out.append(f"{f['key']} | {f['severity']} | {f['rule_id']} | {f['title']} | "
                   f"{f['fix']['label'] if f.get('fix') else 'none'}")
    if not findings:
        out.append("none")
    return "\n".join(out)


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": required}}}


TARGET = {"type": "string", "description": "Component id (e.g. E7) or its tag if unique (e.g. P-102)."}
LINE = {"type": "string", "description": "Pipe id (e.g. L12) or its line number."}

TOOLS = [
    _fn("get_drawing", "Get the current drawing: components, pipes, title block and findings.", {}, []),
    _fn("run_checks", "Run the deterministic rule engine on the current drawing and list findings.", {}, []),
    _fn("move_component", "Move a component to absolute x,y or by dx,dy. Attached pipe ends follow.",
        {"target": TARGET, "x": {"type": "number"}, "y": {"type": "number"}, "dx": {"type": "number"},
         "dy": {"type": "number"}}, ["target"]),
    _fn("rotate_component", "Set a component's rotation in degrees (counter-clockwise).",
        {"target": TARGET, "angle": {"type": "number"}}, ["target", "angle"]),
    _fn("set_tag", "Set or change the tag of a component (e.g. P-102) or the line number of a pipe.",
        {"target": {"type": "string", "description": "Component or pipe id/tag."}, "tag": {"type": "string"}},
        ["target", "tag"]),
    _fn("delete", "Delete a component or pipe. Deleting an inline valve rejoins the pipe.",
        {"target": {"type": "string", "description": "Component or pipe id/tag."},
         "remove_dead_end_pipes": {"type": "boolean", "description": "Also remove pipe stubs left leading nowhere."}},
        ["target"]),
    _fn("add_component", "Add a new symbol. Prefer placing it with `near` + `side`; the tool finds a clear spot.",
        {"type": {"type": "string", "enum": COMPONENT_TYPES}, "tag": {"type": "string", "description": "ISA tag, e.g. LT-101."},
         "near": TARGET, "side": {"type": "string", "enum": ["right", "left", "above", "below"]},
         "distance": {"type": "number", "description": "Gap from the `near` component, drawing units."},
         "x": {"type": "number"}, "y": {"type": "number"}}, ["type"]),
    _fn("connect", "Draw an orthogonal pipe (process) or instrument signal line between two components.",
        {"from_component": TARGET, "to_component": TARGET, "kind": {"type": "string", "enum": ["process", "signal"]},
         "line_number": {"type": "string"}}, ["from_component", "to_component"]),
    _fn("insert_inline", "Insert a valve or inline instrument into an existing pipe, splitting it. Use `after` "
        "(downstream of) or `before` (upstream of) a component, optionally with `line` to pick which pipe.",
        {"type": {"type": "string", "enum": INLINE_TYPES}, "tag": {"type": "string"}, "after": TARGET,
         "before": TARGET, "line": LINE}, ["type"]),
    _fn("extend_pipe", "Extend the start or end of a pipe to meet a component (closes a gap).",
        {"line": LINE, "end": {"type": "string", "enum": ["start", "end"]}, "to_component": TARGET},
        ["line", "end", "to_component"]),
    _fn("set_line_number", "Give a pipe a line number; omit number to use the next in the drawing's series.",
        {"line": LINE, "number": {"type": "string"}}, ["line"]),
    _fn("set_title_block", "Fill in a title block field.",
        {"field": {"type": "string", "enum": TITLE_FIELDS}, "value": {"type": "string"}}, ["field", "value"]),
    _fn("apply_fix", "Apply the automatic fix of one finding (use the key from run_checks).",
        {"issue_key": {"type": "string"}}, ["issue_key"]),
    _fn("apply_all_fixes", "Apply every available automatic fix, re-checking between fixes.", {}, []),
]


def summarize_change(wb: Workbench) -> str:
    return "; ".join(wb.messages) if wb.messages else "no changes"


__all__ = ["Workbench", "TOOLS", "describe_drawing", "summarize_change", "describe"]
