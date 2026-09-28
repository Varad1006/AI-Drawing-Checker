"""Deterministic P&ID rule engine.

Each rule inspects the document (and, for DXF input, the connectivity graph) and emits findings:

    {"key", "rule_id", "source": "rule", "category", "severity", "title", "description",
     "recommendation", "confidence", "entities": [...], "lines": [...], "bbox", "location",
     "fix": {"label": str, "ops": [...]} | None}

`key` is a stable fingerprint (rule + object ids), so a finding keeps its identity across edits and
we can tell when an edit made it go away.

To add a rule: write a function taking a Ctx, decorate it with @rule(...), and call ctx.add(...).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Callable

from ..core import geometry as g
from ..core import topology
from ..core.document import describe, entity_bbox, title_block_prims
from ..core.symbols import (
    ISOLATION_VALVES, LEVEL_HOLDING, TAG_RE, TITLE_FIELDS, TITLE_FIELD_LABELS, TYPES, category, default_prefix,
    line_tag_head, needs_tag, next_free_tag, next_line_tag, normalize_tag, parse_tag, tag_valid_for_type,
)

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


@dataclass
class Rule:
    id: str
    title: str
    category: str
    severity: str
    description: str
    needs_topology: bool
    fn: Callable


RULES: list[Rule] = []


def rule(id: str, title: str, category: str, severity: str, description: str, needs_topology: bool = False):
    def wrap(fn):
        RULES.append(Rule(id, title, category, severity, description, needs_topology, fn))
        return fn
    return wrap


class Ctx:
    def __init__(self, doc: dict):
        self.doc = doc
        self.connectivity = doc.get("meta", {}).get("connectivity", True)
        self.topo = topology.build(doc)
        self.ents = [e for e in doc["entities"]]
        self.by_id = {e["id"]: e for e in self.ents}
        self.types = {e["id"]: e["type"] for e in self.ents}
        self.boxes = {e["id"]: entity_bbox(doc, e) for e in self.ents}
        self.tags = {e["tag"] for e in self.ents if e.get("tag")}
        self.findings: list[dict] = []
        self.rule: Rule | None = None

    def lines_box(self, line_ids):
        box = None
        for ln in self.doc["lines"]:
            if ln["id"] in line_ids:
                box = g.bbox_union(box, g.bbox_of_points(ln["pts"]))
        return box

    def add(self, title, description, recommendation, entities=(), lines=(), box=None, fix=None, extra="",
            severity=None):
        r = self.rule
        entities, lines = list(entities), list(lines)
        if box is None:
            for eid in entities[:1]:
                box = g.bbox_union(box, self.boxes[eid])
            if box is None:
                box = self.lines_box(lines)
        key = f"{r.id}:{'+'.join(sorted(entities + lines))}{':' + extra if extra else ''}"
        self.findings.append({
            "key": key, "rule_id": r.id, "source": "rule", "category": r.category,
            "severity": severity or r.severity, "title": title, "description": description,
            "recommendation": recommendation, "confidence": 1.0, "entities": entities, "lines": lines,
            "bbox": box, "location": g.bbox_center(box) if box else None, "fix": fix,
        })

    def near(self, eid: str, pred, factor: float = 1.0) -> list[str]:
        box = self.boxes[eid]
        w, h = g.bbox_size(box)
        zone = g.bbox_expand(box, factor * max(w, h))
        return [o["id"] for o in self.ents if o["id"] != eid and pred(o)
                and g.bbox_overlap_area(zone, self.boxes[o["id"]]) > 0]


# ---------------------------------------------------------------------------------------------------
# Tagging
# ---------------------------------------------------------------------------------------------------

@rule("R001", "Duplicate tag", "Tagging", "HIGH",
      "Every equipment, valve and instrument tag must be unique on the drawing.")
def duplicate_tags(ctx: Ctx):
    groups = defaultdict(list)
    for e in ctx.ents:
        if e.get("tag"):
            groups[e["tag"]].append(e)
    for tag, ents in groups.items():
        if len(ents) < 2:
            continue
        ents.sort(key=lambda e: int(e["id"][1:]) if e["id"][1:].isdigit() else 0)
        first = ents[0]
        used = set(ctx.tags)
        for dup in ents[1:]:
            parsed = parse_tag(tag)
            fix = None
            if parsed:
                new = next_free_tag(parsed[0], used, start=parsed[1] + 1, width=len(TAG_RE.match(tag).group(2)))
                used.add(new)
                fix = {"label": f"Renumber to {new}", "ops": [{"op": "set_tag", "id": dup["id"], "tag": new}]}
            ctx.add(
                f"Duplicate tag {tag}",
                f"Tag {tag} is used by {len(ents)} components ({', '.join(e['id'] for e in ents)}). "
                f"This {TYPES.get(dup['type'], {}).get('name', dup['type']).lower()} repeats the tag of {first['id']}.",
                "Give each component a unique tag; a standby unit normally takes the next number in the series.",
                entities=[dup["id"], first["id"]], fix=fix,
            )


@rule("R002", "Non-standard tag format", "Tagging", "MEDIUM",
      "Tags must follow the ISA-5.1 form PREFIX-NUMBER, e.g. P-101, FT-101, HV-102.")
def tag_format(ctx: Ctx):
    for e in ctx.ents:
        tag = e.get("tag")
        if not tag or TAG_RE.match(tag):
            continue
        fixed = normalize_tag(tag)
        fix = None
        if TAG_RE.match(fixed) and fixed not in ctx.tags:
            fix = {"label": f"Rename to {fixed}", "ops": [{"op": "set_tag", "id": e["id"], "tag": fixed}]}
        ctx.add(
            f'Tag "{tag}" is not in standard format',
            f'"{tag}" does not match PREFIX-NUMBER (upper case letters, hyphen, 2–4 digits).',
            f"Rename to {fixed}." if fix else "Rename using the project tagging procedure.",
            entities=[e["id"]], fix=fix,
        )


@rule("R003", "Tag prefix does not match symbol", "Tagging", "MEDIUM",
      "The tag prefix must agree with the symbol, e.g. a pump symbol tagged P-xxx, a tank TK-xxx.")
def tag_prefix(ctx: Ctx):
    for e in ctx.ents:
        tag = e.get("tag")
        if not tag or not TAG_RE.match(tag) or tag_valid_for_type(tag, e["type"]) or not e.get("block"):
            continue
        parsed = parse_tag(tag)
        prefix = default_prefix(e["type"])
        fix = None
        if prefix and parsed:
            new = f"{prefix}-{tag.split('-')[1]}"
            if new in ctx.tags:
                new = next_free_tag(prefix, ctx.tags, start=parsed[1])
            fix = {"label": f"Retag as {new}", "ops": [{"op": "set_tag", "id": e["id"], "tag": new}]}
        expected = ", ".join(TYPES[e["type"]]["prefixes"]) or "an instrument prefix (e.g. FT, LT, PI)"
        ctx.add(
            f"{tag} is drawn as a {TYPES[e['type']]['name'].lower()}",
            f"The symbol is a {TYPES[e['type']]['name'].lower()} but the tag prefix '{parsed[0]}' does not match "
            f"(expected {expected}).",
            "Correct either the symbol or the tag so they agree.",
            entities=[e["id"]], fix=fix,
        )


@rule("R004", "Untagged component", "Tagging", "MEDIUM",
      "Equipment, instruments, control valves and relief valves must carry a tag.")
def untagged(ctx: Ctx):
    for e in ctx.ents:
        if e.get("tag") or not needs_tag(e["type"]):
            continue
        prefix = default_prefix(e["type"])
        fix = None
        if prefix:
            new = next_free_tag(prefix, ctx.tags)
            fix = {"label": f"Tag as {new}", "ops": [{"op": "set_tag", "id": e["id"], "tag": new}]}
        ctx.add(
            f"Untagged {TYPES[e['type']]['name'].lower()}",
            f"{e['id']} is a {TYPES[e['type']]['name'].lower()} with no tag, so it cannot be referenced in "
            "datasheets, loop diagrams or the equipment list.",
            "Assign the next tag in the series.",
            entities=[e["id"]], fix=fix,
        )


# ---------------------------------------------------------------------------------------------------
# Connectivity
# ---------------------------------------------------------------------------------------------------

@rule("R005", "Unconnected equipment", "Connectivity", "HIGH",
      "Every piece of process equipment must be connected to at least one process line.", needs_topology=True)
def unconnected_equipment(ctx: Ctx):
    for e in ctx.ents:
        if category(e["type"]) == "equipment" and not ctx.topo.is_connected(e["id"], "process"):
            ctx.add(
                f"{describe(e)} is not connected",
                f"{describe(e)} has no process line attached. Either piping is missing or the symbol is stray.",
                "Route the inlet/outlet piping to this equipment, or delete it if it is not part of the scheme.",
                entities=[e["id"]],
            )


@rule("R006", "Open pipe end", "Connectivity", "MEDIUM",
      "Process lines must terminate at equipment, a valve, another line or an off-page connector.",
      needs_topology=True)
def dangling(ctx: Ctx):
    reach = 8 * ctx.topo.tol
    for lid, end, p in ctx.topo.dangling:
        ln = next(x for x in ctx.doc["lines"] if x["id"] == lid)
        best, best_d = None, None
        for e in ctx.ents:
            box = ctx.boxes[e["id"]]
            dx = max(box[0] - p[0], 0, p[0] - box[2])
            dy = max(box[1] - p[1], 0, p[1] - box[3])
            d = (dx * dx + dy * dy) ** 0.5
            if d <= reach and (best_d is None or d < best_d):
                best, best_d = e, d
        name = ln.get("tag") or f"line {lid}"
        fix = None
        if best:
            fix = {"label": f"Connect to {describe(best)}",
                   "ops": [{"op": "extend_line", "id": lid, "end": end, "to": best["id"]}]}
            desc = f"The {end} of {name} stops {best_d:.1f} units short of {describe(best)} — a missing connection."
        else:
            desc = f"The {end} of {name} ends in open space."
        size = 4 * ctx.topo.tol
        ctx.add(
            f"Open pipe end on {name}",
            desc,
            "Terminate the line properly: connect it, cap it, or add an off-page connector.",
            lines=[lid], entities=[best["id"]] if best else [], box=[p[0] - size, p[1] - size, p[0] + size, p[1] + size],
            fix=fix, extra=end,
        )


# ---------------------------------------------------------------------------------------------------
# Safety / operability
# ---------------------------------------------------------------------------------------------------

EQUIPMENT_TYPES = {t for t, m in TYPES.items() if m["category"] == "equipment"} | {"off_page"}


def _pump_branches(ctx: Ctx, pump: dict) -> list[dict]:
    brs = ctx.topo.branches(pump["id"], EQUIPMENT_TYPES, ctx.types)
    for br in brs:
        br["types"] = [ctx.types.get(n) for n in br["nodes"] if n.startswith("E")]
        br["role"] = "discharge" if br["outgoing"] else "suction"
    if brs and len({b["outgoing"] for b in brs}) == 1:  # line order gives no usable flow direction
        for br in brs:
            br["role"] = "suction" if ctx.types.get(br["end"]) in LEVEL_HOLDING else "discharge"
    return brs


@rule("R007", "Pump discharge without check valve", "Safety", "HIGH",
      "A centrifugal pump needs a check (non-return) valve on its discharge to prevent reverse flow, "
      "especially where pumps run in parallel.", needs_topology=True)
def pump_check_valve(ctx: Ctx):
    for pump in (e for e in ctx.ents if e["type"] == "pump"):
        brs = _pump_branches(ctx, pump)
        if not brs or any("check_valve" in br["types"] for br in brs):
            continue
        discharge = next((b for b in brs if b["role"] == "discharge"), brs[0])
        fix = None
        if discharge["first_line"]:
            fix = {"label": "Insert check valve on discharge", "ops": [
                {"op": "insert_inline", "type": "check_valve", "after": pump["id"], "line": discharge["first_line"]}]}
        ctx.add(
            f"No check valve on {describe(pump)} discharge",
            f"{describe(pump)} discharge has no non-return valve before the next junction or equipment. "
            "Backflow can spin the pump in reverse when it trips.",
            "Install a check valve directly downstream of the pump, upstream of the discharge isolation valve.",
            entities=[pump["id"]], lines=[discharge["first_line"]] if discharge["first_line"] else [], fix=fix,
        )


@rule("R008", "Pump without isolation valve", "Operability", "MEDIUM",
      "Pump suction and discharge must each have an isolation valve so the pump can be removed for "
      "maintenance.", needs_topology=True)
def pump_isolation(ctx: Ctx):
    for pump in (e for e in ctx.ents if e["type"] == "pump"):
        for br in _pump_branches(ctx, pump):
            if ISOLATION_VALVES & set(br["types"]):
                continue
            fix = None
            if br["first_line"]:
                where = "after" if br["outgoing"] or br["role"] == "discharge" else "before"
                fix = {"label": f"Insert gate valve on {br['role']}", "ops": [
                    {"op": "insert_inline", "type": "gate_valve", where: pump["id"], "line": br["first_line"]}]}
            ctx.add(
                f"No isolation valve on {describe(pump)} {br['role']}",
                f"The {br['role']} side of {describe(pump)} cannot be isolated.",
                f"Add a gate or ball valve on the {br['role']} line.",
                entities=[pump["id"]], lines=[br["first_line"]] if br["first_line"] else [], fix=fix, extra=br["role"],
            )


@rule("R009", "Vessel without level instrument", "Instrumentation", "HIGH",
      "Tanks and vessels need a level measurement (LT/LI/LG) to prevent overflow or running dry.")
def level_instrument(ctx: Ctx):
    for e in ctx.ents:
        if e["type"] not in LEVEL_HOLDING:
            continue
        is_level = lambda o: category(o["type"]) == "instrument" and (o.get("tag") or "").upper().startswith("L")  # noqa: E731
        linked = [n for n in ctx.topo.neighbours(e["id"]) if is_level(ctx.by_id[n])] if ctx.connectivity else []
        if linked or ctx.near(e["id"], is_level, 0.6):
            continue
        parsed = parse_tag(e.get("tag"))
        lt = next_free_tag("LT", ctx.tags, start=parsed[1] if parsed else 101)
        fix = {"label": f"Add {lt} with nozzle connection", "ops": [
            {"op": "add_entity", "ref": "lt", "type": "instrument", "tag": lt, "near": e["id"], "side": "right"},
            {"op": "connect", "from": e["id"], "to": "$lt", "kind": "process"},
        ]}
        ctx.add(
            f"{describe(e)} has no level instrument",
            f"No level transmitter, indicator or gauge is connected to or mounted on {describe(e)}.",
            f"Add a level transmitter ({lt}) with high/low alarms.",
            entities=[e["id"]], fix=fix,
        )


@rule("R010", "Pressure vessel without relief valve", "Safety", "CRITICAL",
      "Every pressure vessel must be protected by a pressure safety valve (PSV).")
def vessel_psv(ctx: Ctx):
    for e in ctx.ents:
        if e["type"] != "vessel":
            continue
        is_psv = lambda o: o["type"] == "relief_valve"  # noqa: E731
        if ctx.connectivity:
            protected = any(ctx.types.get(n) == "relief_valve" for n in ctx.topo.neighbours(e["id"]))
        else:
            protected = bool(ctx.near(e["id"], is_psv, 0.6))
        if protected:
            continue
        parsed = parse_tag(e.get("tag"))
        psv = next_free_tag("PSV", ctx.tags, start=parsed[1] if parsed else 101)
        fix = {"label": f"Add {psv} on top of {describe(e)}", "ops": [
            {"op": "add_entity", "ref": "psv", "type": "relief_valve", "tag": psv, "near": e["id"], "side": "above"},
            {"op": "connect", "from": e["id"], "to": "$psv", "kind": "process"},
        ]}
        ctx.add(
            f"{describe(e)} has no pressure safety valve",
            f"{describe(e)} is a pressure vessel with no PSV connected. Overpressure (blocked outlet, fire case) "
            "would be unprotected.",
            f"Add {psv} on the vessel top, sized for the governing relief case.",
            entities=[e["id"]], fix=fix,
        )


# ---------------------------------------------------------------------------------------------------
# Instrumentation
# ---------------------------------------------------------------------------------------------------

@rule("R011", "Control valve without control loop", "Instrumentation", "MEDIUM",
      "A control valve (FV/LV/PV/TV) needs a measuring instrument or controller with the same loop number.")
def control_loop(ctx: Ctx):
    for e in ctx.ents:
        if e["type"] != "control_valve":
            continue
        parsed = parse_tag(e.get("tag"))
        if not parsed or parsed[0] == "XV":
            continue
        letter, number = parsed[0][0], parsed[1]
        loop = [o for o in ctx.ents if category(o["type"]) == "instrument" and (p := parse_tag(o.get("tag")))
                and p[0][0] == letter and p[1] == number]
        if loop:
            continue
        ctx.add(
            f"{e['tag']} has no matching loop instrument",
            f"No {letter}T-{number} transmitter or {letter}IC-{number} controller exists, so nothing drives {e['tag']}.",
            f"Add the loop instruments ({letter}T-{number}, {letter}IC-{number}) or correct the valve tag.",
            entities=[e["id"]],
        )


@rule("R012", "Instrument not connected", "Instrumentation", "LOW",
      "Instruments must connect to the process (impulse/nozzle line) or to their loop (signal line).",
      needs_topology=True)
def instrument_connected(ctx: Ctx):
    for e in ctx.ents:
        if category(e["type"]) != "instrument" or ctx.topo.is_connected(e["id"]) or e["id"] in ctx.topo.inline:
            continue
        ctx.add(
            f"{describe(e)} is not connected",
            f"{describe(e)} has no process or signal line attached.",
            "Draw its process connection and/or signal line to the controller.",
            entities=[e["id"]],
        )


# ---------------------------------------------------------------------------------------------------
# Documentation / layout
# ---------------------------------------------------------------------------------------------------

def _runs(ctx: Ctx) -> list[list[str]]:
    """Group process line pieces that are split only by inline valves into one pipe run."""
    parent = {ln["id"]: ln["id"] for ln in ctx.doc["lines"] if ln.get("kind", "process") == "process"}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for eid, attached in ctx.topo.attachments.items():
        if category(ctx.types.get(eid, "")) != "valve":
            continue
        pids = [lid for lid, _ in attached if lid in parent]
        for a, b in zip(pids, pids[1:]):
            parent[find(a)] = find(b)
    runs = defaultdict(list)
    for lid in parent:
        runs[find(lid)].append(lid)
    return list(runs.values())


def _neighbour_line_head(ctx: Ctx, run: list[str], by_id: dict) -> str | None:
    """Size-service prefix of a numbered pipe on the equipment this run connects to."""
    for lid in run:
        for end in ("start", "end"):
            node = ctx.topo.ends[lid][end]
            if category(ctx.types.get(node, "")) != "equipment":
                continue
            for other, _ in ctx.topo.attachments.get(node, []):
                head = line_tag_head(by_id[other].get("tag")) if other not in run else None
                if head:
                    return head
    return None


@rule("R013", "Line without line number", "Documentation", "LOW",
      "Every process pipe run needs a line number (size-service-sequence, e.g. 50-RW-1001).", needs_topology=True)
def line_numbers(ctx: Ctx):
    by_id = {ln["id"]: ln for ln in ctx.doc["lines"]}
    existing = [ln.get("tag") for ln in ctx.doc["lines"] if ln.get("tag")]
    for run in _runs(ctx):
        if any(by_id[lid].get("tag") for lid in run):
            continue
        touches_instrument = any(
            category(ctx.types.get(ctx.topo.ends[lid][end], "")) == "instrument" or
            ctx.types.get(ctx.topo.ends[lid][end]) == "relief_valve"
            for lid in run for end in ("start", "end")
        )
        if touches_instrument:
            continue  # impulse / relief connections are numbered with their instrument
        longest = max(run, key=lambda lid: g.polyline_length(by_id[lid]["pts"]))
        new = next_line_tag(existing, _neighbour_line_head(ctx, run, by_id))
        existing.append(new)
        ctx.add(
            "Pipe run has no line number",
            f"The run {' → '.join(sorted(run))} carries no line number, so it cannot be traced to the line list.",
            f"Label it with the next number in the series ({new}).",
            lines=sorted(run), fix={"label": f"Number as {new}", "ops": [{"op": "set_line_number", "id": longest, "tag": new}]},
        )


@rule("R014", "Title block incomplete", "Documentation", "LOW",
      "The title block must state title, drawing number, revision, drawn by, checked by and date.")
def title_block(ctx: Ctx):
    tb = ctx.doc.get("title_block")
    if not tb:
        b = ctx.doc["bounds"]
        ctx.add("No title block found", "The drawing has no recognisable title block.",
                "Insert the project title block and fill in all fields.",
                box=[b[2] - (b[2] - b[0]) * 0.3, b[1], b[2], b[1] + (b[3] - b[1]) * 0.15])
        return
    missing = [f for f in TITLE_FIELDS if not (tb.get("fields", {}).get(f, {}).get("value") or "").strip()]
    if missing:
        names = ", ".join(TITLE_FIELD_LABELS[f] for f in missing)
        ctx.add(
            f"Title block missing {names}",
            f"The title block has empty fields: {names}.",
            "Complete the title block before issue; the checker's name and date record who approved it.",
            box=g.bbox_of(title_block_prims(ctx.doc)), extra=",".join(missing),
        )


@rule("R015", "Overlapping symbols", "Layout", "LOW",
      "Symbols must not overlap; overlapping symbols are ambiguous and hard to read.")
def overlaps(ctx: Ctx):
    ents = [e for e in ctx.ents if e.get("block")]
    for i, a in enumerate(ents):
        for b in ents[i + 1:]:
            ba, bb = ctx.boxes[a["id"]], ctx.boxes[b["id"]]
            area = g.bbox_overlap_area(ba, bb)
            smaller = min(g.bbox_size(ba)[0] * g.bbox_size(ba)[1], g.bbox_size(bb)[0] * g.bbox_size(bb)[1]) or 1
            if area < 0.25 * smaller:
                continue
            ca, cb = g.bbox_center(ba), g.bbox_center(bb)
            if abs(cb[0] - ca[0]) >= abs(cb[1] - ca[1]):
                sign = 1 if cb[0] >= ca[0] else -1
                dx = (ba[2] - bb[0] + 4 * ctx.topo.tol) if sign > 0 else -(bb[2] - ba[0] + 4 * ctx.topo.tol)
                move = {"op": "move", "id": b["id"], "dx": round(dx, 3), "dy": 0}
            else:
                sign = 1 if cb[1] >= ca[1] else -1
                dy = (ba[3] - bb[1] + 4 * ctx.topo.tol) if sign > 0 else -(bb[3] - ba[1] + 4 * ctx.topo.tol)
                move = {"op": "move", "id": b["id"], "dx": 0, "dy": round(dy, 3)}
            ctx.add(
                f"{describe(a)} overlaps {describe(b)}",
                f"The symbols of {describe(a)} and {describe(b)} overlap.",
                f"Move {describe(b)} clear of {describe(a)}.",
                entities=[b["id"], a["id"]], box=g.bbox_union(ba, bb),
                fix={"label": f"Move {describe(b)} clear", "ops": [move]},
            )


# ---------------------------------------------------------------------------------------------------

def run_rules(doc: dict) -> list[dict]:
    ctx = Ctx(doc)
    for r in RULES:
        if r.needs_topology and not ctx.connectivity:
            continue
        ctx.rule = r
        r.fn(ctx)
    ctx.findings.sort(key=lambda f: (SEVERITY_ORDER.get(f["severity"], 9), f["rule_id"], f["key"]))
    return ctx.findings


def catalog() -> list[dict]:
    return [{"id": r.id, "title": r.title, "category": r.category, "severity": r.severity,
             "description": r.description, "needs_topology": r.needs_topology} for r in RULES]
