"""The drawing document: the single JSON structure every revision stores.

    {
      "version": 1,
      "source": {"format": "dxf" | "pdf", "units": "mm"},
      "bounds": [minx, miny, maxx, maxy],
      "blocks": {name: [primitive, ...]},                  # block-local symbol geometry
      "entities": [{"id", "type", "tag", "block", "x", "y", "rot", "sx", "sy", "layer",
                    "label": {"dx", "dy", "h", "rot", "style"} | None, "attrs": {}}],
      "lines": [{"id", "kind": "process" | "signal", "pts": [[x, y], ...], "tag", "layer",
                 "tag_pos": {"p", "h", "rot"} | None}],        # pts are ordered in flow direction
      "background": [primitive, ...],                         # geometry we render but do not reason about
      "title_block": {"block", "x", "y", "sx", "sy", "rot", "fields": {name: {"value", "p", "h"}}} | None,
      "meta": {"connectivity": bool, "seq": {"E": n, "L": n}}
    }
"""
from __future__ import annotations

import statistics

from . import geometry as g
from .symbols import TYPES


def entity_local_box(doc: dict, ent: dict) -> list[float]:
    prims = doc["blocks"].get(ent.get("block") or "", [])
    box = g.bbox_of(prims)
    if box is None:
        return ent.get("box") or [-3.0, -3.0, 3.0, 3.0]  # text-only components may carry a measured size
    return box


def entity_bbox(doc: dict, ent: dict) -> list[float]:
    """World-space bounding box of a component's symbol (label excluded)."""
    x0, y0, x1, y1 = entity_local_box(doc, ent)
    corners = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    return g.bbox_of_points(
        g.transform_point(c, ent["x"], ent["y"], ent.get("rot", 0), ent.get("sx", 1), ent.get("sy", 1)) for c in corners
    )


def label_prim(ent: dict) -> dict | None:
    lab, tag = ent.get("label"), ent.get("tag")
    if not lab or not tag:
        return None
    return {
        "t": "text", "p": [ent["x"] + lab["dx"], ent["y"] + lab["dy"]], "s": tag, "h": lab["h"],
        "rot": lab.get("rot", 0), "ha": "center", "va": "middle",
    }


def line_tag_prim(ln: dict, h: float = 2.0) -> dict | None:
    """Line number text: where the source drawing put it, else along the longest straight segment."""
    if not ln.get("tag"):
        return None
    tp = ln.get("tag_pos")
    if tp:
        return {"t": "text", "p": tp["p"], "s": ln["tag"], "h": tp.get("h", h), "rot": tp.get("rot", 0),
                "ha": tp.get("ha", "left"), "va": tp.get("va", "baseline")}
    pts = ln["pts"]
    i = max(range(len(pts) - 1), key=lambda k: g.dist(pts[k], pts[k + 1]))
    a, b = pts[i], pts[i + 1]
    mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]
    if abs(a[0] - b[0]) >= abs(a[1] - b[1]):
        return {"t": "text", "p": [mid[0], mid[1] + 0.6 * h], "s": ln["tag"], "h": h, "rot": 0, "ha": "center", "va": "baseline"}
    return {"t": "text", "p": [mid[0] - 0.6 * h, mid[1]], "s": ln["tag"], "h": h, "rot": 90, "ha": "center", "va": "baseline"}


def entity_world_prims(doc: dict, ent: dict) -> list[dict]:
    prims = [
        g.transform_prim(p, ent["x"], ent["y"], ent.get("rot", 0), ent.get("sx", 1), ent.get("sy", 1))
        for p in doc["blocks"].get(ent.get("block") or "", [])
    ]
    return prims


def title_block_prims(doc: dict) -> list[dict]:
    tb = doc.get("title_block")
    if not tb:
        return []
    prims = []
    if tb.get("block"):
        prims += [
            g.transform_prim(p, tb["x"], tb["y"], tb.get("rot", 0), tb.get("sx", 1), tb.get("sy", 1))
            for p in doc["blocks"].get(tb["block"], [])
        ]
    for field in tb.get("fields", {}).values():
        if field.get("value"):
            prims.append({"t": "text", "p": field["p"], "s": field["value"], "h": field["h"], "rot": 0,
                          "ha": "left", "va": "baseline"})
    return prims


def find_entity(doc: dict, ent_id: str) -> dict | None:
    return next((e for e in doc["entities"] if e["id"] == ent_id), None)


def find_line(doc: dict, line_id: str) -> dict | None:
    return next((ln for ln in doc["lines"] if ln["id"] == line_id), None)


def new_id(doc: dict, kind: str) -> str:
    seq = doc.setdefault("meta", {}).setdefault("seq", {})
    if kind not in seq:
        pool = doc["entities"] if kind == "E" else doc["lines"]
        seq[kind] = max([int(x["id"][1:]) for x in pool if x["id"][1:].isdigit()] or [0])
    seq[kind] += 1
    return f"{kind}{seq[kind]}"


def symbol_boxes(doc: dict) -> list[list[float]]:
    return [entity_bbox(doc, e) for e in doc["entities"] if e.get("block")]


def snap_tolerance(doc: dict) -> float:
    """How close a pipe end must be to a symbol to count as connected, scaled to the drawing."""
    sizes = [min(g.bbox_size(b)) for b in symbol_boxes(doc)]
    sizes = [s for s in sizes if s > 0]
    if sizes:
        return max(0.25, 0.2 * statistics.median(sizes))
    b = doc.get("bounds") or [0, 0, 100, 100]
    return max(0.25, 0.004 * max(b[2] - b[0], b[3] - b[1]))


def symbol_scale(doc: dict) -> float:
    """Scale to apply to built-in symbols so new components match the drawing's own symbol size."""
    builtin_ref = 12.0  # typical built-in symbol span in mm
    spans = [max(g.bbox_size(b)) for b in symbol_boxes(doc)]
    spans = [s for s in spans if s > 0]
    if not spans:
        b = doc.get("bounds") or [0, 0, 420, 297]
        return max(0.05, max(b[2] - b[0], b[3] - b[1]) / 420)
    scales = [e.get("sx", 1) for e in doc["entities"] if e.get("block") in _builtin_names()]
    if scales:
        return statistics.median(scales)
    return statistics.median(spans) / builtin_ref


def text_height(doc: dict) -> float:
    hs = [e["label"]["h"] for e in doc["entities"] if e.get("label")]
    return statistics.median(hs) if hs else 2.5 * symbol_scale(doc)


def _builtin_names() -> set[str]:
    return {meta["block"] for meta in TYPES.values()}


def recompute_bounds(doc: dict) -> list[float]:
    box = None
    for e in doc["entities"]:
        box = g.bbox_union(box, entity_bbox(doc, e))
        lab = label_prim(e)
        if lab:
            box = g.bbox_union(box, g.prim_bbox(lab))
    for ln in doc["lines"]:
        box = g.bbox_union(box, g.bbox_of_points(ln["pts"]))
    box = g.bbox_union(box, g.bbox_of(doc["background"]))
    box = g.bbox_union(box, g.bbox_of(title_block_prims(doc)))
    doc["bounds"] = box or [0.0, 0.0, 420.0, 297.0]
    return doc["bounds"]


def describe(ent: dict) -> str:
    return ent.get("tag") or f"untagged {TYPES.get(ent['type'], {}).get('name', ent['type']).lower()} ({ent['id']})"


def empty_document(fmt: str = "dxf", units: str = "mm") -> dict:
    return {
        "version": 1,
        "source": {"format": fmt, "units": units},
        "bounds": [0.0, 0.0, 420.0, 297.0],
        "blocks": {},
        "entities": [],
        "lines": [],
        "background": [],
        "title_block": None,
        "meta": {"connectivity": fmt == "dxf", "seq": {"E": 0, "L": 0}},
    }
