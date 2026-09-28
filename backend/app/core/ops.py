"""Edit operations: the only way a drawing changes.

Manual canvas edits, rule auto-fixes and AI tool calls all produce the same JSON ops, e.g.

    {"op": "set_tag", "id": "E7", "tag": "P-102"}
    {"op": "insert_inline", "line": "L12", "after": "E7", "type": "check_valve", "tag": "NRV-102"}
    {"op": "add_entity", "ref": "lt", "type": "instrument", "tag": "LT-101", "near": "E1", "side": "right"}
    {"op": "connect", "from": "E1", "to": "$lt", "kind": "process"}

Targets may be ids ("E7", "L3"), unique tags ("P-102", "50-RW-1001") or "$ref" names bound by an
earlier op in the same batch.
"""
from __future__ import annotations

import copy
import math

from . import geometry as g
from . import topology
from .document import (
    entity_bbox, entity_local_box, find_entity, find_line, new_id, recompute_bounds, symbol_scale, text_height,
    describe,
)
from .symbols import (
    BUILTIN_BLOCKS, TITLE_FIELD_POS, TITLE_FIELDS, TYPES, category, default_label, default_prefix, needs_tag,
    next_free_tag, parse_tag, next_line_tag, prefix_type,
)

EPS = 1e-6
SIDES = {"right": (1, 0), "left": (-1, 0), "above": (0, 1), "below": (0, -1)}


class OpError(ValueError):
    pass


class EditResult:
    def __init__(self, doc: dict):
        self.doc = doc
        self.changed: set[str] = set()
        self.messages: list[str] = []
        self.refs: dict[str, str] = {}


# ---------------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------------

def resolve(doc: dict, target, refs: dict[str, str], want: str | None = None) -> dict:
    """Find an entity ("E") or line ("L") by id, $ref or unique tag."""
    if target is None:
        raise OpError("missing target")
    target = str(target).strip()
    if target.startswith("$"):
        if target[1:] not in refs:
            raise OpError(f"unknown reference {target}")
        target = refs[target[1:]]
    if want != "L":
        ent = find_entity(doc, target)
        if ent:
            return ent
    if want != "E":
        ln = find_line(doc, target)
        if ln:
            return ln
    norm = target.upper()
    ents = [e for e in doc["entities"] if (e.get("tag") or "").upper() == norm] if want != "L" else []
    lines = [ln for ln in doc["lines"] if (ln.get("tag") or "").upper() == norm] if want != "E" else []
    if len(ents) == 1:
        return ents[0]
    if len(ents) > 1:
        raise OpError(f"tag {target} is used by {len(ents)} components ({', '.join(e['id'] for e in ents)}); use an id")
    if lines:
        return max(lines, key=lambda ln: g.polyline_length(ln["pts"]))
    raise OpError(f"no {'line' if want == 'L' else 'component'} matches '{target}'")


def _is_line(obj: dict) -> bool:
    return "pts" in obj


def _ensure_block(doc: dict, type_: str) -> str:
    block = TYPES[type_]["block"]
    if block not in doc["blocks"]:
        doc["blocks"][block] = copy.deepcopy(BUILTIN_BLOCKS[block])
    return block


def _shift_line_end(ln: dict, end: str, dx: float, dy: float) -> None:
    pts = ln["pts"]
    i, j = (0, 1) if end == "start" else (len(pts) - 1, len(pts) - 2)
    p, q = pts[i], pts[j]
    horizontal, vertical = abs(p[1] - q[1]) < EPS, abs(p[0] - q[0]) < EPS
    new_p = [p[0] + dx, p[1] + dy]
    if len(pts) == 2:
        pts[i] = new_p
        a, b = pts
        if horizontal and abs(a[1] - b[1]) > EPS:
            mx = (a[0] + b[0]) / 2
            ln["pts"] = [a, [mx, a[1]], [mx, b[1]], b]
        elif vertical and abs(a[0] - b[0]) > EPS:
            my = (a[1] + b[1]) / 2
            ln["pts"] = [a, [a[0], my], [b[0], my], b]
    else:
        if horizontal:
            q[1] += dy
        elif vertical:
            q[0] += dx
        pts[i] = new_p
    ln["pts"] = g.simplify_polyline(ln["pts"])
    if len(ln["pts"]) < 2:
        ln["pts"] = [new_p, [new_p[0] + EPS * 10, new_p[1]]]
    if ln.get("tag_pos") and len(ln["pts"]) >= 2:
        ln["tag_pos"] = None  # re-derived by the renderer from the longest segment


def _port(doc: dict, ent: dict, toward: list[float]) -> tuple[list[float], str]:
    """Connection point on the side of the symbol facing `toward`."""
    box = entity_bbox(doc, ent)
    cx, cy = ent["x"], ent["y"]
    dx, dy = toward[0] - cx, toward[1] - cy
    if abs(dx) >= abs(dy):
        y = toward[1] if box[1] < toward[1] < box[3] else cy
        return [box[2] if dx > 0 else box[0], y], "h"
    x = toward[0] if box[0] < toward[0] < box[2] else cx
    return [x, box[3] if dy > 0 else box[1]], "v"


def _free_spot(doc: dict, near: dict, type_: str, side: str, distance: float | None, sc: float) -> list[float]:
    """First position on the requested side of `near` that clears other symbols and pipes."""
    ux, uy = SIDES[side]
    nb = entity_bbox(doc, near)
    lb = [v * sc for v in g.bbox_of(BUILTIN_BLOCKS[TYPES[type_]["block"]])]
    gap = distance if distance is not None else (8 if category(type_) == "instrument" else 10) * sc
    if ux:
        x0 = (nb[2] - lb[0] + gap) if ux > 0 else (nb[0] - lb[2] - gap)
        y0 = near["y"] + (0.3 * (nb[3] - nb[1]) if category(near["type"]) == "equipment" else 0)
    else:
        y0 = (nb[3] - lb[1] + gap) if uy > 0 else (nb[1] - lb[3] - gap)
        x0 = near["x"]
    others = [entity_bbox(doc, e) for e in doc["entities"] if e["id"] != near["id"]]
    segments = [(ln["pts"][i], ln["pts"][i + 1]) for ln in doc["lines"] for i in range(len(ln["pts"]) - 1)]

    def clear(x, y):
        box = [x + lb[0], y + lb[1], x + lb[2], y + lb[3]]
        if any(g.bbox_overlap_area(g.bbox_expand(box, 2 * sc), o) > 0 for o in others):
            return False
        return not any(g.seg_bbox_clip(a, b, g.bbox_expand(box, 1.5 * sc)) for a, b in segments)

    for k in range(10):
        for perp in (0, 1, -1, 2, -2):
            x = x0 + ux * k * 5 * sc + (0 if ux else perp * 7 * sc)
            y = y0 + uy * k * 5 * sc + (perp * 7 * sc if ux else 0)
            if clear(x, y):
                return [round(x, 3), round(y, 3)]
    return [round(x0, 3), round(y0, 3)]


def _snap_end_to_box(ln: dict, end: str, box: list[float]) -> None:
    pts = ln["pts"]
    i, j = (0, 1) if end == "start" else (len(pts) - 1, len(pts) - 2)
    q, p = pts[j], pts[i]
    far = [p[0] + (p[0] - q[0]) * 10, p[1] + (p[1] - q[1]) * 10]
    clip = g.seg_bbox_clip(q, far, box)
    if clip:
        t = clip[0]
        pts[i] = [q[0] + (far[0] - q[0]) * t, q[1] + (far[1] - q[1]) * t]


def _tag_number(tag: str | None) -> int | None:
    parsed = parse_tag(tag)
    return parsed[1] if parsed else None


def _auto_tag(doc: dict, type_: str, anchor: dict | None = None) -> str | None:
    prefix = default_prefix(type_)
    if not prefix or not needs_tag(type_) and type_ not in ("check_valve", "gate_valve", "globe_valve", "ball_valve"):
        return None
    existing = {e["tag"] for e in doc["entities"] if e.get("tag")}
    start = _tag_number(anchor.get("tag")) if anchor else None
    return next_free_tag(prefix, existing, start=start or 101)


# ---------------------------------------------------------------------------------------------------
# operations
# ---------------------------------------------------------------------------------------------------

def op_move(res: EditResult, op: dict) -> str:
    doc = res.doc
    ent = resolve(doc, op.get("id"), res.refs, "E")
    if "x" in op and "y" in op:
        dx, dy = float(op["x"]) - ent["x"], float(op["y"]) - ent["y"]
    else:
        dx, dy = float(op.get("dx", 0)), float(op.get("dy", 0))
    if abs(dx) < EPS and abs(dy) < EPS:
        return f"{describe(ent)} already at ({ent['x']:.1f}, {ent['y']:.1f})"
    topo = topology.build(doc)
    ent["x"], ent["y"] = round(ent["x"] + dx, 4), round(ent["y"] + dy, 4)
    for lid, end in topo.attachments.get(ent["id"], []):
        ln = find_line(doc, lid)
        _shift_line_end(ln, end, dx, dy)
        res.changed.add(lid)
    res.changed.add(ent["id"])
    return f"Moved {describe(ent)} to ({ent['x']:.1f}, {ent['y']:.1f})"


def op_rotate(res: EditResult, op: dict) -> str:
    doc = res.doc
    ent = resolve(doc, op.get("id"), res.refs, "E")
    topo = topology.build(doc)
    ent["rot"] = float(op.get("angle", 0)) % 360
    box = entity_bbox(doc, ent)
    for lid, end in topo.attachments.get(ent["id"], []):
        _snap_end_to_box(find_line(doc, lid), end, box)
        res.changed.add(lid)
    res.changed.add(ent["id"])
    return f"Rotated {describe(ent)} to {ent['rot']:.0f}°"


def op_set_tag(res: EditResult, op: dict) -> str:
    doc = res.doc
    obj = resolve(doc, op.get("id"), res.refs)
    tag = (op.get("tag") or "").strip().upper() or None
    old = obj.get("tag")
    obj["tag"] = tag
    if not _is_line(obj) and tag and not obj.get("label"):
        obj["label"] = default_label(obj["type"], entity_local_box(doc, obj), text_height(doc))
    res.changed.add(obj["id"])
    return f"Retagged {old or obj['id']} → {tag}"


def op_delete(res: EditResult, op: dict) -> str:
    doc = res.doc
    obj = resolve(doc, op.get("id"), res.refs)
    if _is_line(obj):
        doc["lines"] = [ln for ln in doc["lines"] if ln["id"] != obj["id"]]
        return f"Deleted line {obj.get('tag') or obj['id']}"
    topo = topology.build(doc)
    attached = topo.attachments.get(obj["id"], [])
    doc["entities"] = [e for e in doc["entities"] if e["id"] != obj["id"]]
    msg = f"Deleted {describe(obj)}"
    process = [(lid, end) for lid, end in attached if topo.kind.get(lid) == "process"]
    if category(obj["type"]) in ("valve", "instrument") and len(process) == 2 and op.get("heal", True):
        # an inline valve was removed: stitch the two pipe pieces back together
        (l1, e1), (l2, e2) = process
        a, b = find_line(doc, l1), find_line(doc, l2)
        if a is not b:
            pa = a["pts"] if e1 == "end" else a["pts"][::-1]
            pb = b["pts"] if e2 == "start" else b["pts"][::-1]
            a["pts"] = g.simplify_polyline(pa + pb)
            a["tag"] = a.get("tag") or b.get("tag")
            doc["lines"] = [ln for ln in doc["lines"] if ln["id"] != b["id"]]
            res.changed.add(a["id"])
            msg += " and rejoined the pipe"
    elif op.get("cascade", True):
        # drop pipe stubs that now lead nowhere
        doomed = set()
        for lid, end in attached:
            other = topo.ends[lid]["start" if end == "end" else "end"]
            if other.startswith("F:"):
                doomed.add(lid)
        if doomed:
            doc["lines"] = [ln for ln in doc["lines"] if ln["id"] not in doomed]
            msg += f" and {len(doomed)} dead-end pipe(s)"
    return msg


def op_add_entity(res: EditResult, op: dict) -> str:
    doc = res.doc
    type_ = op.get("type")
    if type_ not in TYPES:
        raise OpError(f"unknown component type '{type_}'. Valid: {', '.join(TYPES)}")
    parsed = parse_tag((op.get("tag") or "").strip().upper())
    if parsed and category(type_) == "instrument" and prefix_type(parsed[0]) in ("instrument", "instrument_panel"):
        type_ = prefix_type(parsed[0])  # LIC-102 is a panel controller, LT-102 a field instrument
    sc = symbol_scale(doc)
    block = _ensure_block(doc, type_)
    near = resolve(doc, op["near"], res.refs, "E") if op.get("near") else None
    if "x" in op and "y" in op and op["x"] is not None and op["y"] is not None:
        x, y = float(op["x"]), float(op["y"])
    elif near:
        side = op.get("side", "right")
        if side not in SIDES:
            raise OpError(f"side must be one of {', '.join(SIDES)}")
        x, y = _free_spot(doc, near, type_, side, op.get("distance"), sc)
    else:
        raise OpError("add_entity needs x/y or a 'near' component")
    tag = (op.get("tag") or "").strip().upper() or _auto_tag(doc, type_, near)
    ent = {
        "id": new_id(doc, "E"), "type": type_, "tag": tag, "block": block, "x": x, "y": y,
        "rot": float(op.get("rot", 0)), "sx": sc, "sy": sc, "layer": category(type_).upper(), "attrs": {},
    }
    local = [v * sc for v in g.bbox_of(doc["blocks"][block])]
    ent["label"] = default_label(type_, local, text_height(doc)) if tag else None
    doc["entities"].append(ent)
    if op.get("ref"):
        res.refs[op["ref"]] = ent["id"]
    res.changed.add(ent["id"])
    return f"Added {TYPES[type_]['name'].lower()} {tag or ent['id']} at ({x:.1f}, {y:.1f})"


def op_add_line(res: EditResult, op: dict) -> str:
    doc = res.doc
    pts = [[float(p[0]), float(p[1])] for p in op.get("pts", [])]
    if len(pts) < 2:
        raise OpError("a line needs at least two points")
    kind = op.get("kind", "process")
    ln = {"id": new_id(doc, "L"), "kind": kind, "pts": g.simplify_polyline(pts), "tag": op.get("tag"),
          "layer": "PIPING" if kind == "process" else "SIGNAL", "tag_pos": None}
    doc["lines"].append(ln)
    if op.get("ref"):
        res.refs[op["ref"]] = ln["id"]
    res.changed.add(ln["id"])
    return f"Drew {kind} line {ln.get('tag') or ln['id']}"


def op_connect(res: EditResult, op: dict) -> str:
    doc = res.doc
    a = resolve(doc, op.get("from"), res.refs, "E")
    b = resolve(doc, op.get("to"), res.refs, "E")
    if a is b:
        raise OpError("cannot connect a component to itself")
    pa, orient = _port(doc, a, [b["x"], b["y"]])
    pb, _ = _port(doc, b, pa)
    if orient == "h" and abs(pa[1] - pb[1]) > EPS and entity_bbox(doc, b)[1] < pa[1] < entity_bbox(doc, b)[3]:
        pb = [pb[0], pa[1]]
    pts = g.orthogonal_route(pa, pb, horizontal_first=(orient == "h"))
    kind = op.get("kind", "process")
    sub = EditResult(doc)
    sub.refs = res.refs
    op_add_line(sub, {"pts": pts, "kind": kind, "tag": op.get("tag"), "ref": op.get("ref")})
    res.changed |= sub.changed | {a["id"], b["id"]}
    return f"Connected {describe(a)} → {describe(b)} with a {kind} line"


def op_insert_inline(res: EditResult, op: dict) -> str:
    doc = res.doc
    type_ = op.get("type")
    if type_ not in TYPES or category(type_) not in ("valve", "instrument"):
        raise OpError("insert_inline needs a valve or instrument type")
    topo = topology.build(doc)
    anchor, from_end = None, "start"
    if op.get("after") or op.get("before"):
        anchor = resolve(doc, op.get("after") or op.get("before"), res.refs, "E")
        want_end = "start" if op.get("after") else "end"
        candidates = [(lid, end) for lid, end in topo.attachments.get(anchor["id"], []) if topo.kind[lid] == "process"]
        if op.get("line"):
            line_obj = resolve(doc, op["line"], res.refs, "L")
            candidates = [c for c in candidates if c[0] == line_obj["id"]] or candidates
        preferred = [c for c in candidates if c[1] == want_end] or candidates
        if not preferred:
            raise OpError(f"{describe(anchor)} has no process line to insert on")
        lid, from_end = preferred[0]
        ln = find_line(doc, lid)
    elif op.get("line"):
        ln = resolve(doc, op["line"], res.refs, "L")
    else:
        raise OpError("insert_inline needs 'line', 'after' or 'before'")

    sc = symbol_scale(doc)
    block = _ensure_block(doc, type_)
    lbox = [v * sc for v in g.bbox_of(doc["blocks"][block])]
    half = (lbox[2] - lbox[0]) / 2
    clearance = 4 * sc
    pts = ln["pts"] if from_end == "start" else ln["pts"][::-1]
    total = g.polyline_length(pts)
    if total < 2 * half + 2 * clearance:
        raise OpError(f"line {ln.get('tag') or ln['id']} is too short ({total:.1f}) to fit a {type_.replace('_', ' ')}")

    if op.get("at"):
        _, seg, t, q = g.point_polyline(op["at"], pts)
        d = g.polyline_length(pts[: seg + 1]) + g.dist(pts[seg], q)
    elif anchor:
        d = half + clearance
    else:
        d = total / 2
    # keep the symbol on a single straight segment
    cum = [0.0]
    for i in range(len(pts) - 1):
        cum.append(cum[-1] + g.dist(pts[i], pts[i + 1]))
    seg = next((i for i in range(len(pts) - 1) if cum[i] <= d <= cum[i + 1]), len(pts) - 2)
    lo, hi = cum[seg] + half + clearance * 0.5, cum[seg + 1] - half - clearance * 0.5
    if lo > hi:
        fits = [i for i in range(len(pts) - 1) if cum[i + 1] - cum[i] >= 2 * half + clearance]
        if not fits:
            raise OpError("no straight run long enough for the new component")
        seg = min(fits, key=lambda i: abs((cum[i] + cum[i + 1]) / 2 - d))
        lo, hi = cum[seg] + half + clearance * 0.5, cum[seg + 1] - half - clearance * 0.5
    d = min(max(d, lo), hi)
    a, b = pts[seg], pts[seg + 1]
    ux, uy = (b[0] - a[0]) / g.dist(a, b), (b[1] - a[1]) / g.dist(a, b)
    centre, _ = g.point_along(pts, d)
    p_in = [centre[0] - ux * half, centre[1] - uy * half]
    p_out = [centre[0] + ux * half, centre[1] + uy * half]
    first = g.simplify_polyline(pts[: seg + 1] + [p_in])
    second = g.simplify_polyline([p_out] + pts[seg + 1:])
    if from_end == "end":  # restore flow order
        first, second = second[::-1], first[::-1]
    ln["pts"] = first
    ln["tag_pos"] = None
    new_line = {"id": new_id(doc, "L"), "kind": ln["kind"], "pts": second, "tag": None, "layer": ln.get("layer"),
                "tag_pos": None}
    doc["lines"].insert(doc["lines"].index(ln) + 1, new_line)

    angle = math.degrees(math.atan2(uy, ux))
    if from_end == "end":
        angle += 180
    tag = (op.get("tag") or "").strip().upper() or _auto_tag(doc, type_, anchor)
    ent = {
        "id": new_id(doc, "E"), "type": type_, "tag": tag, "block": block,
        "x": round(centre[0], 4), "y": round(centre[1], 4), "rot": round(angle % 360, 3), "sx": sc, "sy": sc,
        "layer": category(type_).upper(), "attrs": {},
    }
    label_box = lbox if abs(uy) < 0.5 else [lbox[1], lbox[0], lbox[3], lbox[2]]
    ent["label"] = default_label(type_, label_box, text_height(doc)) if tag else None
    if ent["label"] and abs(uy) >= 0.5 and category(type_) == "valve":  # vertical pipe: tag to the right
        ent["label"].update(dx=label_box[2] + 2 + len(tag) * ent["label"]["h"] * 0.31, dy=0.0)
    doc["entities"].append(ent)
    if op.get("ref"):
        res.refs[op["ref"]] = ent["id"]
    res.changed |= {ent["id"], ln["id"], new_line["id"]}
    where = f"after {describe(anchor)}" if op.get("after") else f"before {describe(anchor)}" if anchor else f"on {ln.get('tag') or ln['id']}"
    return f"Inserted {TYPES[type_]['name'].lower()} {tag or ent['id']} {where}"


def op_extend_line(res: EditResult, op: dict) -> str:
    doc = res.doc
    ln = resolve(doc, op.get("id"), res.refs, "L")
    target = resolve(doc, op.get("to"), res.refs, "E")
    end = op.get("end", "end")
    box = entity_bbox(doc, target)
    pts = ln["pts"]
    i, j = (0, 1) if end == "start" else (len(pts) - 1, len(pts) - 2)
    p, q = pts[i], pts[j]
    if abs(p[1] - q[1]) < EPS and box[1] <= p[1] <= box[3]:          # horizontal run: extend in x
        pts[i] = [box[0] if p[0] < box[0] else box[2], p[1]]
    elif abs(p[0] - q[0]) < EPS and box[0] <= p[0] <= box[2]:        # vertical run: extend in y
        pts[i] = [p[0], box[1] if p[1] < box[1] else box[3]]
    else:
        port, orient = _port(doc, target, p)
        route = g.orthogonal_route(p, port, horizontal_first=(orient == "h"))
        ln["pts"] = pts + route[1:] if end == "end" else route[::-1][:-1] + pts
    ln["pts"] = g.simplify_polyline(ln["pts"])
    res.changed |= {ln["id"], target["id"]}
    return f"Extended {ln.get('tag') or ln['id']} to {describe(target)}"


def op_set_title(res: EditResult, op: dict) -> str:
    doc = res.doc
    field = str(op.get("field", "")).upper()
    if field not in TITLE_FIELDS:
        raise OpError(f"title block field must be one of {', '.join(TITLE_FIELDS)}")
    tb = doc.get("title_block")
    if not tb:
        b = doc["bounds"]
        sc = max(0.2, (b[2] - b[0]) / 420)
        doc["blocks"].setdefault("TITLE_BLOCK", copy.deepcopy(BUILTIN_BLOCKS["TITLE_BLOCK"]))
        tb = doc["title_block"] = {"block": "TITLE_BLOCK", "x": b[2] - 180 * sc, "y": b[1] - 45 * sc, "sx": sc, "sy": sc,
                                   "rot": 0, "fields": {}}
    if field not in tb["fields"]:
        fx, fy, fh = TITLE_FIELD_POS[field]
        tb["fields"][field] = {"value": "", "p": [tb["x"] + fx * tb.get("sx", 1), tb["y"] + fy * tb.get("sy", 1)],
                               "h": fh * tb.get("sy", 1)}
    tb["fields"][field]["value"] = str(op.get("value", "")).strip()
    res.changed.add("title_block")
    return f"Set title block {field} = {tb['fields'][field]['value'] or '(blank)'}"


def op_set_line_number(res: EditResult, op: dict) -> str:
    ln = resolve(res.doc, op.get("id"), res.refs, "L")
    tag = (op.get("tag") or "").strip().upper() or next_line_tag([x.get("tag") for x in res.doc["lines"] if x.get("tag")])
    ln["tag"] = tag
    ln["tag_pos"] = None
    res.changed.add(ln["id"])
    return f"Numbered line {ln['id']} as {tag}"


OPS = {
    "move": op_move,
    "rotate": op_rotate,
    "set_tag": op_set_tag,
    "delete": op_delete,
    "add_entity": op_add_entity,
    "add_line": op_add_line,
    "connect": op_connect,
    "insert_inline": op_insert_inline,
    "extend_line": op_extend_line,
    "set_title": op_set_title,
    "set_line_number": op_set_line_number,
}


def apply_ops(doc: dict, ops: list[dict], refs: dict[str, str] | None = None) -> EditResult:
    """Apply ops to a copy of doc. Raises OpError (with the failing op's index) on the first failure."""
    res = EditResult(copy.deepcopy(doc))
    if refs:
        res.refs.update(refs)
    for n, op in enumerate(ops):
        fn = OPS.get(op.get("op"))
        if not fn:
            raise OpError(f"op {n + 1}: unknown operation '{op.get('op')}'")
        try:
            res.messages.append(fn(res, op))
        except OpError as exc:
            raise OpError(f"op {n + 1} ({op.get('op')}): {exc}") from exc
    recompute_bounds(res.doc)
    return res
