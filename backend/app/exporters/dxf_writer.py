"""Drawing document -> DXF.

`build_dxf(doc)` writes the drawing back out as proper CAD: block definitions with a TAG attribute
definition, one INSERT per component (tag as an attribute), pipes as LWPOLYLINEs on PIPING / SIGNAL
layers, line numbers, background geometry and the title block with its attributes.

With `issues`, a CHECKER layer is added holding a revision cloud and numbered balloon per finding,
plus a findings legend beside the drawing — the classic lead-checker mark-up.
"""
from __future__ import annotations

import io

import ezdxf
from ezdxf.enums import TextEntityAlignment

from ..core import geometry as g
from ..core.document import line_tag_prim
from ..core.symbols import category

ALIGN = {
    ("left", "baseline"): TextEntityAlignment.LEFT, ("center", "baseline"): TextEntityAlignment.CENTER,
    ("right", "baseline"): TextEntityAlignment.RIGHT, ("left", "middle"): TextEntityAlignment.MIDDLE_LEFT,
    ("center", "middle"): TextEntityAlignment.MIDDLE_CENTER, ("right", "middle"): TextEntityAlignment.MIDDLE_RIGHT,
    ("left", "top"): TextEntityAlignment.TOP_LEFT, ("center", "top"): TextEntityAlignment.TOP_CENTER,
    ("right", "top"): TextEntityAlignment.TOP_RIGHT,
}
LAYERS = {  # name: (ACI colour, linetype)
    "EQUIPMENT": (7, "CONTINUOUS"), "VALVE": (3, "CONTINUOUS"), "INSTRUMENT": (4, "CONTINUOUS"),
    "CONNECTOR": (7, "CONTINUOUS"), "PIPING": (7, "CONTINUOUS"), "SIGNAL": (8, "DASHED"), "LINE_NO": (7, "CONTINUOUS"),
    "TITLE": (7, "CONTINUOUS"), "CHECKER": (1, "CONTINUOUS"),
}
UNITS = {"in": 1, "ft": 2, "mm": 4, "cm": 5, "m": 6}
SEVERITY_ACI = {"CRITICAL": 1, "HIGH": 30, "MEDIUM": 2, "LOW": 5}
CLOUD_BULGE = 0.55  # positive = counter-clockwise arcs, i.e. bumps outward on a CCW outline


def _layer(dxf, name: str) -> str:
    name = name or "0"
    if not dxf.layers.has_entry(name):
        color, ltype = LAYERS.get(name.upper(), (7, "CONTINUOUS"))
        dxf.layers.add(name, color=color, linetype=ltype)
    return name


def _add_prim(dxf, layout, p: dict, layer: str) -> None:
    attribs = {"layer": _layer(dxf, p.get("layer") or layer)}
    if p.get("ls") == "dashed":
        attribs["linetype"] = "DASHED"
    t = p["t"]
    if t == "line":
        layout.add_line(p["a"], p["b"], dxfattribs=attribs)
    elif t == "poly":
        if p.get("fill"):
            hatch = layout.add_hatch(color=7, dxfattribs={"layer": attribs["layer"]})
            hatch.paths.add_polyline_path(p["pts"], is_closed=True)
        layout.add_lwpolyline(p["pts"], close=bool(p.get("closed")), dxfattribs=attribs)
    elif t == "circle":
        if p.get("fill"):
            hatch = layout.add_hatch(color=7, dxfattribs={"layer": attribs["layer"]})
            hatch.paths.add_polyline_path(g.arc_points(p["c"], p["r"], 0, 360, 15), is_closed=True)
        layout.add_circle(p["c"], p["r"], dxfattribs=attribs)
    elif t == "arc":
        layout.add_arc(p["c"], p["r"], p["a0"], p["a1"], dxfattribs=attribs)
    elif t == "text":
        text = layout.add_text(p["s"], height=p.get("h", 2.5), rotation=p.get("rot", 0), dxfattribs=attribs)
        text.set_placement(p["p"], align=ALIGN.get((p.get("ha", "left"), p.get("va", "baseline")), TextEntityAlignment.LEFT))


def build_dxf(doc: dict, issues: list[dict] | None = None) -> ezdxf.document.Drawing:
    dxf = ezdxf.new("R2018", setup=True)
    dxf.header["$INSUNITS"] = UNITS.get(doc["source"].get("units"), 0)
    for name in LAYERS:
        _layer(dxf, name)
    msp = dxf.modelspace()
    tb = doc.get("title_block")

    for name, prims in doc["blocks"].items():
        blk = dxf.blocks.new(name=name)
        for p in prims:
            _add_prim(dxf, blk, p, "0")
        if tb and name == tb.get("block"):
            for field in tb.get("fields", {}):
                blk.add_attdef(field, (0, 0), dxfattribs={"height": 2.5})
        else:
            blk.add_attdef("TAG", (0, 0), dxfattribs={"height": 2.5})

    for p in doc["background"]:
        _add_prim(dxf, msp, p, "0")

    for ln in doc["lines"]:
        layer = "PIPING" if ln.get("kind", "process") == "process" else "SIGNAL"
        attribs = {"layer": _layer(dxf, layer)}
        if layer == "SIGNAL":
            attribs["linetype"] = "DASHED"
        msp.add_lwpolyline(ln["pts"], dxfattribs=attribs)
        tag = line_tag_prim(ln)
        if tag:
            _add_prim(dxf, msp, {**tag, "layer": "LINE_NO"}, "LINE_NO")

    for e in doc["entities"]:
        layer = _layer(dxf, category(e["type"]).upper())
        lab = e.get("label") or {}
        if e.get("block") and e["block"] in doc["blocks"]:
            ref = msp.add_blockref(e["block"], (e["x"], e["y"]), dxfattribs={
                "rotation": e.get("rot", 0), "xscale": e.get("sx", 1), "yscale": e.get("sy", 1), "layer": layer})
            if e.get("tag"):
                pos = (e["x"] + lab.get("dx", 0), e["y"] + lab.get("dy", 0))
                h = lab.get("h", 2.5) * (0.75 if lab.get("style") == "split" else 1)
                att = ref.add_attrib("TAG", e["tag"], insert=pos, dxfattribs={"height": h, "layer": layer,
                                                                               "rotation": lab.get("rot", 0)})
                att.set_placement(pos, align=TextEntityAlignment.MIDDLE_CENTER)
            for k, v in (e.get("attrs") or {}).items():
                att = ref.add_attrib(str(k)[:255], str(v), insert=(e["x"], e["y"]), dxfattribs={"height": 1, "layer": layer})
                att.is_invisible = True
        elif e.get("tag"):
            pos = (e["x"] + lab.get("dx", 0), e["y"] + lab.get("dy", 0))
            msp.add_text(e["tag"], height=lab.get("h", 2.5), dxfattribs={"layer": layer}).set_placement(
                pos, align=TextEntityAlignment.MIDDLE_CENTER)

    if tb:
        if tb.get("block") and tb["block"] in doc["blocks"]:
            ref = msp.add_blockref(tb["block"], (tb["x"], tb["y"]), dxfattribs={
                "rotation": tb.get("rot", 0), "xscale": tb.get("sx", 1), "yscale": tb.get("sy", 1), "layer": "TITLE"})
            for field, f in tb.get("fields", {}).items():
                ref.add_attrib(field, f.get("value", ""), insert=f["p"], dxfattribs={"height": f["h"], "layer": "TITLE"})
        else:
            for f in tb.get("fields", {}).values():
                if f.get("value"):
                    msp.add_text(f["value"], height=f["h"], dxfattribs={"layer": "TITLE"}).set_placement(f["p"])

    if issues:
        _markup(dxf, msp, doc, issues)
    return dxf


def _markup(dxf, msp, doc: dict, issues: list[dict]) -> None:
    b = doc["bounds"]
    scale = max(b[2] - b[0], b[3] - b[1]) / 420
    arc = 4 * scale
    for n, iss in enumerate(issues, 1):
        if not iss.get("bbox"):
            continue
        box = g.bbox_expand(iss["bbox"], 3 * scale)
        color = SEVERITY_ACI.get(iss["severity"], 1)
        pts = [(p[0], p[1], CLOUD_BULGE) for p in g.cloud_points(box, arc)]
        msp.add_lwpolyline(pts, format="xyb", close=True, dxfattribs={"layer": "CHECKER", "color": color})
        bx, by = box[0], box[3]
        msp.add_circle((bx, by), 3.2 * scale, dxfattribs={"layer": "CHECKER", "color": color})
        msp.add_text(str(n), height=3 * scale, dxfattribs={"layer": "CHECKER", "color": color}).set_placement(
            (bx, by), align=TextEntityAlignment.MIDDLE_CENTER)
    x, y = b[2] + 15 * scale, b[3]
    msp.add_text("LEAD CHECKER FINDINGS", height=4 * scale, dxfattribs={"layer": "CHECKER"}).set_placement((x, y))
    for n, iss in enumerate(issues, 1):
        y -= 7 * scale
        status = f" [{iss['status']}]" if iss.get("status") and iss["status"] != "OPEN" else ""
        text = f"{n}. {iss['severity']} {iss['rule_id']}: {iss['title']}{status}"
        msp.add_text(text, height=2.6 * scale, dxfattribs={"layer": "CHECKER", "color": SEVERITY_ACI.get(iss["severity"], 1)}
                     ).set_placement((x, y))


def dxf_bytes(doc: dict, issues: list[dict] | None = None) -> bytes:
    stream = io.StringIO()
    build_dxf(doc, issues).write(stream)
    return stream.getvalue().encode("utf-8")
