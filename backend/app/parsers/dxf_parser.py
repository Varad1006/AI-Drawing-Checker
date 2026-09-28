"""DXF -> drawing document.

Model space is read as follows:
  * INSERTs whose block name (or TAG attribute) identifies a P&ID symbol become components; their
    block geometry is kept once per block so the viewer can draw the real symbol.
  * A title-block INSERT fills the document's title block fields from its attributes.
  * Open LINE / LWPOLYLINE / POLYLINE on non-annotation layers become pipes; dashed linetypes or
    signal/instrument layers make them signal lines. Pieces that chain end-to-end are merged.
  * TEXT / MTEXT is matched to untagged symbols (including split "FT" / "101" instrument bubbles),
    to pipes as line numbers, or becomes a text-only component when it is a stand-alone tag.
  * Everything else is kept as background geometry so the drawing still renders faithfully.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict

import ezdxf
from ezdxf import path as ezpath
from ezdxf import recover

from ..core import geometry as g
from ..core.document import empty_document, entity_bbox, new_id, recompute_bounds, snap_tolerance
from ..core.symbols import (
    LINE_TAG_RE, LOOSE_TAG_RE, category, classify_block, looks_like_tag, prefix_type,
)

logger = logging.getLogger(__name__)


class ParseError(ValueError):
    pass


BACKGROUND_LAYER_RE = re.compile(r"BORDER|FRAME|TITLE|NOTE|TEXT|DIM|ANNO|GRID|SHEET|HATCH|CHECK|DEFPOINTS|VIEWPORT", re.I)
SIGNAL_LAYER_RE = re.compile(r"SIGNAL|INSTR|ELEC|CTRL|CONTROL|IMPULSE|PNEUM", re.I)
DASHED_RE = re.compile(r"DASH|HIDDEN|DOT|PHANTOM|CENTER|DIVIDE", re.I)
TAG_ATTRIBS = ("TAG", "TAGNO", "TAG_NO", "TAGNUMBER", "TAG_NUMBER", "ITEM", "NAME", "ID")
TITLE_ALIASES = {
    "TITLE": "TITLE", "DWG_TITLE": "TITLE", "DRAWING_TITLE": "TITLE",
    "DWG_NO": "DWG_NO", "DWGNO": "DWG_NO", "DRAWING_NO": "DWG_NO", "DRAWING_NUMBER": "DWG_NO", "DWG_NUMBER": "DWG_NO",
    "REV": "REV", "REVISION": "REV", "REV_NO": "REV",
    "DRAWN": "DRAWN_BY", "DRAWN_BY": "DRAWN_BY", "DRN": "DRAWN_BY", "DRAWNBY": "DRAWN_BY",
    "CHECKED": "CHECKED_BY", "CHECKED_BY": "CHECKED_BY", "CHK": "CHECKED_BY", "CHECKEDBY": "CHECKED_BY",
    "DATE": "DATE",
}
UNITS = {0: "unitless", 1: "in", 2: "ft", 4: "mm", 5: "cm", 6: "m"}
TEXT_HA = {0: "left", 1: "center", 2: "right", 3: "center", 4: "center", 5: "center"}
TEXT_VA = {0: "baseline", 1: "baseline", 2: "middle", 3: "top"}
MTEXT_ATTACH = {1: ("left", "top"), 2: ("center", "top"), 3: ("right", "top"), 4: ("left", "middle"),
                5: ("center", "middle"), 6: ("right", "middle"), 7: ("left", "baseline"), 8: ("center", "baseline"),
                9: ("right", "baseline")}


def parse_dxf(file_path: str) -> dict:
    try:
        dxf, auditor = recover.readfile(file_path)
    except (OSError, ezdxf.DXFStructureError) as exc:
        raise ParseError(f"Not a readable DXF file: {exc}") from exc
    if auditor.has_errors:
        logger.warning("DXF had %d structural errors; recovered what we could", len(auditor.errors))
    return _DXFReader(dxf).run()


def _xy(v) -> list[float]:
    return [round(float(v[0]), 6), round(float(v[1]), 6)]


class _DXFReader:
    def __init__(self, dxf):
        self.dxf = dxf
        self.doc = empty_document("dxf", UNITS.get(dxf.header.get("$INSUNITS", 0), "unitless"))

    # ---- primitive conversion ----------------------------------------------------------------------

    def _dashed(self, e) -> bool:
        lt = e.dxf.get("linetype", "BYLAYER") or "BYLAYER"
        if lt.upper() in ("BYLAYER", "BYBLOCK"):
            layer = self.dxf.layers.get(e.dxf.get("layer", "0")) if self.dxf.layers.has_entry(e.dxf.get("layer", "0")) else None
            lt = layer.dxf.get("linetype", "CONTINUOUS") if layer else "CONTINUOUS"
        return bool(DASHED_RE.search(lt))

    def _text(self, e) -> list[dict]:
        extra = {"layer": e.dxf.get("layer", "0")}
        if e.dxftype() in ("TEXT", "ATTRIB"):
            s = e.plain_text().strip()
            if not s:
                return []
            ha, va = TEXT_HA.get(e.dxf.get("halign", 0), "left"), TEXT_VA.get(e.dxf.get("valign", 0), "baseline")
            if e.dxf.get("halign", 0) == 4:
                va = "middle"
            aligned = e.dxf.get("halign", 0) or e.dxf.get("valign", 0)
            p = e.dxf.get("align_point") if aligned and e.dxf.hasattr("align_point") else e.dxf.insert
            return [{"t": "text", "p": _xy(p), "s": s, "h": float(e.dxf.get("height", 2.5)),
                     "rot": float(e.dxf.get("rotation", 0)), "ha": ha, "va": va, **extra}]
        # MTEXT
        lines = [ln.strip() for ln in e.plain_text().split("\n") if ln.strip()]
        if not lines:
            return []
        h = float(e.dxf.get("char_height", 2.5))
        ha, va = MTEXT_ATTACH.get(e.dxf.get("attachment_point", 1), ("left", "top"))
        rot = float(e.get_rotation()) if hasattr(e, "get_rotation") else float(e.dxf.get("rotation", 0))
        p0 = _xy(e.dxf.insert)
        n, step = len(lines), 1.6 * h
        out = []
        for i, s in enumerate(lines):
            if va == "top":
                off = -i * step
            elif va == "middle":
                off = (n - 1) * step / 2 - i * step
            else:
                off = (n - 1 - i) * step
            dp = g.rotate([0, off], rot)
            out.append({"t": "text", "p": [p0[0] + dp[0], p0[1] + dp[1]], "s": s, "h": h, "rot": rot, "ha": ha,
                        "va": va, **extra})
        return out

    def prims(self, e, depth: int = 0) -> list[dict]:
        t = e.dxftype()
        extra = {"layer": e.dxf.get("layer", "0")}
        if self._dashed(e):
            extra["ls"] = "dashed"
        try:
            if t == "LINE":
                return [{"t": "line", "a": _xy(e.dxf.start), "b": _xy(e.dxf.end), **extra}]
            if t in ("LWPOLYLINE", "POLYLINE"):
                if t == "POLYLINE" and (e.is_poly_face_mesh or e.is_polygon_mesh):
                    return []
                closed = e.closed if t == "LWPOLYLINE" else e.is_closed
                pts = [_xy(v) for v in ezpath.make_path(e).flattening(0.1)]
                if closed and len(pts) > 2 and g.dist(pts[0], pts[-1]) < 1e-9:
                    pts = pts[:-1]
                return [{"t": "poly", "pts": pts, "closed": bool(closed), **extra}] if len(pts) >= 2 else []
            if t == "CIRCLE":
                return [{"t": "circle", "c": _xy(e.dxf.center), "r": float(e.dxf.radius), **extra}]
            if t == "ARC":
                return [{"t": "arc", "c": _xy(e.dxf.center), "r": float(e.dxf.radius),
                         "a0": float(e.dxf.start_angle), "a1": float(e.dxf.end_angle), **extra}]
            if t in ("ELLIPSE", "SPLINE"):
                pts = [_xy(v) for v in ezpath.make_path(e).flattening(0.1)]
                return [{"t": "poly", "pts": pts, "closed": False, **extra}] if len(pts) >= 2 else []
            if t in ("TEXT", "MTEXT", "ATTRIB"):
                return self._text(e)
            if t in ("SOLID", "TRACE"):
                v = [_xy(e.dxf.vtx0), _xy(e.dxf.vtx1), _xy(e.dxf.vtx3), _xy(e.dxf.vtx2)]
                return [{"t": "poly", "pts": v, "closed": True, "fill": True, **extra}]
            if t == "HATCH":
                out = []
                for p in ezpath.from_hatch(e):
                    pts = [_xy(v) for v in p.flattening(0.1)]
                    if len(pts) >= 3:
                        out.append({"t": "poly", "pts": pts, "closed": True, "fill": e.dxf.get("solid_fill", 0) == 1, **extra})
                return out
            if t == "INSERT" and depth < 8:
                out = []
                for v in e.virtual_entities():
                    out += self.prims(v, depth + 1)
                for a in e.attribs:
                    if not a.is_invisible:
                        out += self._text(a)
                return out
            if t in ("DIMENSION", "LEADER", "MULTILEADER", "MLEADER") and depth < 8:
                out = []
                for v in e.virtual_entities():
                    out += self.prims(v, depth + 1)
                return out
        except Exception as exc:  # a single malformed entity must not sink the whole drawing
            logger.debug("skipping %s: %s", t, exc)
        return []

    def block_prims(self, name: str) -> list[dict]:
        if name in self.doc["blocks"]:
            return self.doc["blocks"][name]
        blk = self.dxf.blocks.get(name)
        prims: list[dict] = []
        if blk is not None:
            base = blk.block.dxf.get("base_point", (0, 0, 0))
            for be in blk:
                if be.dxftype() == "ATTDEF":
                    continue
                prims += self.prims(be, 1)
            if base[0] or base[1]:
                prims = [g.transform_prim(p, -base[0], -base[1]) for p in prims]
        self.doc["blocks"][name] = prims
        return prims

    # ---- model space ---------------------------------------------------------------------------------

    def run(self) -> dict:
        texts: list[dict] = []
        pipes: list[tuple[list[list[float]], str, str]] = []
        count = 0
        for e in self.dxf.modelspace():
            count += 1
            t = e.dxftype()
            layer = e.dxf.get("layer", "0")
            if t == "INSERT":
                self._insert(e)
            elif t in ("TEXT", "MTEXT"):
                texts += self.prims(e)
            elif t in ("LINE", "LWPOLYLINE", "POLYLINE") and not BACKGROUND_LAYER_RE.search(layer):
                for p in self.prims(e):
                    if p["t"] == "line":
                        pts = [p["a"], p["b"]]
                    elif p["t"] == "poly" and not p.get("closed") and not self._has_arc(e):
                        pts = p["pts"]
                    else:
                        self.doc["background"].append(p)
                        continue
                    kind = "signal" if SIGNAL_LAYER_RE.search(layer) or p.get("ls") == "dashed" else "process"
                    pipes.append((pts, kind, layer))
            else:
                self.doc["background"] += self.prims(e)
        if count == 0:
            raise ParseError("The DXF model space is empty.")
        self._merge_pipes(pipes)
        self._assign_texts(texts)
        recompute_bounds(self.doc)
        return self.doc

    @staticmethod
    def _has_arc(e) -> bool:
        if e.dxftype() == "LWPOLYLINE":
            return bool(e.has_arc)
        if e.dxftype() == "POLYLINE":
            return any(v.dxf.get("bulge", 0) for v in e.vertices)
        return False

    def _insert(self, e) -> None:
        name = e.dxf.name
        type_ = classify_block(name)
        attribs = {a.dxf.tag.upper(): a for a in e.attribs}
        tag_attrib = next((attribs[k] for k in TAG_ATTRIBS if k in attribs and attribs[k].dxf.text.strip()), None)
        if type_ is None and tag_attrib is not None:
            m = LOOSE_TAG_RE.match(tag_attrib.dxf.text.strip())
            type_ = prefix_type(m.group(1)) if m else None
        if type_ is None:
            self.doc["background"] += self.prims(e)
            return
        self.block_prims(name)
        ins = _xy(e.dxf.insert)
        placement = {"x": ins[0], "y": ins[1], "rot": float(e.dxf.get("rotation", 0)),
                     "sx": float(e.dxf.get("xscale", 1)), "sy": float(e.dxf.get("yscale", 1))}
        if type_ == "title_block":
            fields = {}
            for key, a in attribs.items():
                field = TITLE_ALIASES.get(key)
                if field:
                    t = self._text(a)
                    fields[field] = {"value": a.dxf.text.strip(), "p": t[0]["p"] if t else _xy(a.dxf.insert),
                                     "h": float(a.dxf.get("height", 2.5))}
            self.doc["title_block"] = {"block": name, **placement, "fields": fields}
            return
        ent = {"id": new_id(self.doc, "E"), "type": type_, "tag": None, "block": name, **placement,
               "layer": e.dxf.get("layer", "0"), "label": None,
               "attrs": {k: a.dxf.text for k, a in attribs.items() if a is not tag_attrib}}
        if tag_attrib is not None:
            ent["tag"] = tag_attrib.dxf.text.strip()
            t = self._text(tag_attrib)
            if t:
                ent["label"] = self._label_from_text(ent, t[0])
        self.doc["entities"].append(ent)

    def _label_from_text(self, ent: dict, t: dict) -> dict:
        box = g.text_box(t)
        c = g.bbox_center(box)
        style = "single"
        if category(ent["type"]) == "instrument" and ent.get("block"):
            eb = entity_bbox(self.doc, ent)
            if g.bbox_contains(eb, c):
                style = "split"
                c = [ent["x"], ent["y"]]
        return {"dx": round(c[0] - ent["x"], 4), "dy": round(c[1] - ent["y"], 4), "h": t["h"], "rot": t.get("rot", 0),
                "style": style}

    def _merge_pipes(self, pipes) -> None:
        tol = snap_tolerance(self.doc)
        q = max(tol * 0.05, 1e-6)
        key = lambda p: (round(p[0] / q), round(p[1] / q))  # noqa: E731
        pieces = []
        for pts, kind, layer in pipes:
            for a, b in zip(pts, pts[1:]):
                if g.dist(a, b) > 1e-9:
                    pieces.append((a, b, kind, layer))
        deg = defaultdict(list)
        for i, (a, b, kind, _) in enumerate(pieces):
            deg[(key(a), kind)].append(i)
            deg[(key(b), kind)].append(i)
        used = [False] * len(pieces)

        def extend(chain, idx_from_end):
            while True:
                tail = chain[-1]
                nodes = deg[(key(tail), kind)]
                if len(nodes) != 2:
                    return chain
                nxt = next((i for i in nodes if not used[i]), None)
                if nxt is None:
                    return chain
                used[nxt] = True
                a, b = pieces[nxt][0], pieces[nxt][1]
                chain.append(b if key(a) == key(tail) else a)

        for i, (a, b, kind, layer) in enumerate(pieces):
            if used[i]:
                continue
            used[i] = True
            fwd = extend([a, b], 0)
            back = extend([a], 0)  # walk backwards from a
            pts = back[::-1][:-1] + fwd if len(back) > 1 else fwd
            self.doc["lines"].append({"id": new_id(self.doc, "L"), "kind": kind, "pts": g.simplify_polyline(pts),
                                      "tag": None, "layer": layer, "tag_pos": None})

    def _assign_texts(self, texts: list[dict]) -> None:
        remaining = list(texts)
        tol = snap_tolerance(self.doc)
        centre = lambda t: g.bbox_center(g.text_box(t))  # noqa: E731

        # 1. split instrument bubbles: "FT" over "101"
        for e in self.doc["entities"]:
            if e.get("tag") or category(e["type"]) != "instrument":
                continue
            box = entity_bbox(self.doc, e)
            inside = [t for t in remaining if g.bbox_contains(box, centre(t))]
            letters = [t for t in inside if re.fullmatch(r"[A-Z]{1,4}", t["s"].strip())]
            numbers = [t for t in inside if re.fullmatch(r"\d{2,4}[A-Z]?", t["s"].strip())]
            if letters and numbers:
                e["tag"] = f"{letters[0]['s'].strip()}-{numbers[0]['s'].strip()}"
                e["label"] = {"dx": 0.0, "dy": 0.0, "h": letters[0]["h"], "rot": 0, "style": "split"}
                remaining = [t for t in remaining if t is not letters[0] and t is not numbers[0]]
            else:
                tagged = next((t for t in inside if looks_like_tag(t["s"])), None)
                if tagged:
                    e["tag"] = tagged["s"].strip()
                    e["label"] = self._label_from_text(e, tagged)
                    remaining = [t for t in remaining if t is not tagged]

        # 2. nearest free tag text for other untagged symbols
        for e in self.doc["entities"]:
            if e.get("tag") or not e.get("block"):
                continue
            box = entity_bbox(self.doc, e)
            reach = max(g.bbox_size(box)) + tol
            best, best_d = None, None
            for t in remaining:
                if not looks_like_tag(t["s"]):
                    continue
                c = centre(t)
                dx = max(box[0] - c[0], 0, c[0] - box[2])
                dy = max(box[1] - c[1], 0, c[1] - box[3])
                d = (dx * dx + dy * dy) ** 0.5
                ttype = prefix_type(LOOSE_TAG_RE.match(t["s"].strip()).group(1))
                same_kind = category(ttype) == category(e["type"])
                if d <= (reach if same_kind else reach * 0.5) and (best_d is None or d < best_d):
                    best, best_d = t, d
            if best:
                e["tag"] = best["s"].strip()
                e["label"] = self._label_from_text(e, best)
                remaining = [t for t in remaining if t is not best]

        # 3. line numbers
        process = [ln for ln in self.doc["lines"] if ln["kind"] == "process"]
        for t in list(remaining):
            s = t["s"].strip()
            if not LINE_TAG_RE.match(s) or not process:
                continue
            c = centre(t)
            ln = min(process, key=lambda x: g.point_polyline(c, x["pts"])[0])
            if g.point_polyline(c, ln["pts"])[0] <= 3 * t["h"] + tol and not ln.get("tag"):
                ln["tag"] = s
                ln["tag_pos"] = {"p": t["p"], "h": t["h"], "rot": t.get("rot", 0), "ha": t.get("ha", "left"),
                                 "va": t.get("va", "baseline")}
                remaining.remove(t)

        # 4. stand-alone tags become text-only components
        tagged = {e["tag"].upper() for e in self.doc["entities"] if e.get("tag")}
        for t in list(remaining):
            s = t["s"].strip()
            if not looks_like_tag(s) or s.upper() in tagged:
                continue
            type_ = prefix_type(LOOSE_TAG_RE.match(s).group(1))
            c = centre(t)
            self.doc["entities"].append({
                "id": new_id(self.doc, "E"), "type": type_, "tag": s, "block": None, "x": c[0], "y": c[1],
                "rot": 0.0, "sx": 1.0, "sy": 1.0, "layer": t.get("layer", "0"),
                "label": {"dx": 0.0, "dy": 0.0, "h": t["h"], "rot": t.get("rot", 0), "style": "single"}, "attrs": {},
            })
            remaining.remove(t)

        self.doc["background"] += remaining
