"""Vector PDF -> drawing document (first page).

PDFs exported from CAD keep their text and vector paths but lose block and layer structure, so a PDF
gives us tags, symbol outlines and geometry to render, but no reliable pipe connectivity. The
document is flagged `meta.connectivity = False` and the rule engine skips graph-based rules; tag,
instrumentation-by-proximity, title block and layout rules still run.
"""
from __future__ import annotations

import math
import re

import pymupdf

from ..core import geometry as g
from ..core.document import empty_document, new_id, recompute_bounds
from ..core.symbols import LOOSE_TAG_RE, category, is_instrument_prefix, looks_like_tag, prefix_type
from .dxf_parser import ParseError

PT_TO_MM = 25.4 / 72


def parse_pdf(file_path: str) -> dict:
    try:
        pdf = pymupdf.open(file_path)
    except Exception as exc:
        raise ParseError(f"Not a readable PDF file: {exc}") from exc
    if pdf.page_count == 0:
        raise ParseError("The PDF has no pages.")
    page = pdf[0]
    height = page.rect.height
    conv = lambda x, y: [round(x * PT_TO_MM, 4), round((height - y) * PT_TO_MM, 4)]  # noqa: E731

    doc = empty_document("pdf", "mm")
    doc["meta"]["connectivity"] = False
    doc["meta"]["pages"] = pdf.page_count

    texts: list[dict] = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            s = "".join(span["text"] for span in line["spans"]).strip()
            if not s:
                continue
            x0, y0, x1, y1 = line["bbox"]
            size = max(span["size"] for span in line["spans"])
            cos, sin = line.get("dir", (1, 0))
            rot = round(-math.degrees(math.atan2(sin, cos)), 3) % 360
            texts.append({"t": "text", "p": conv(x0, y1 - 0.2 * size), "s": s, "h": size * 0.72 * PT_TO_MM,
                          "rot": rot, "ha": "left", "va": "baseline"})

    closed_boxes: list[list[float]] = []
    for path in page.get_drawings():
        dashed = bool(path.get("dashes")) and path["dashes"] not in ("[] 0", "[] 0.0")
        fill = path.get("fill") is not None
        for item in path["items"]:
            kind = item[0]
            if kind == "l":
                prim = {"t": "line", "a": conv(item[1].x, item[1].y), "b": conv(item[2].x, item[2].y)}
            elif kind == "re":
                r = item[1]
                prim = {"t": "poly", "pts": [conv(r.x0, r.y0), conv(r.x1, r.y0), conv(r.x1, r.y1), conv(r.x0, r.y1)],
                        "closed": True, "fill": fill}
            elif kind == "qu":
                q = item[1]
                prim = {"t": "poly", "pts": [conv(q.ul.x, q.ul.y), conv(q.ur.x, q.ur.y), conv(q.lr.x, q.lr.y),
                                             conv(q.ll.x, q.ll.y)], "closed": True, "fill": fill}
            elif kind == "c":
                p0, c1, c2, p3 = item[1:5]
                pts = []
                for i in range(9):
                    t = i / 8
                    x = (1 - t) ** 3 * p0.x + 3 * (1 - t) ** 2 * t * c1.x + 3 * (1 - t) * t * t * c2.x + t ** 3 * p3.x
                    y = (1 - t) ** 3 * p0.y + 3 * (1 - t) ** 2 * t * c1.y + 3 * (1 - t) * t * t * c2.y + t ** 3 * p3.y
                    pts.append(conv(x, y))
                prim = {"t": "poly", "pts": pts, "closed": False, "fill": fill}
            else:
                continue
            if dashed:
                prim["ls"] = "dashed"
            doc["background"].append(prim)
        if path.get("closePath") or any(it[0] in ("re", "qu", "c") for it in path["items"]):
            r = path["rect"]
            closed_boxes.append(g.bbox_of_points([conv(r.x0, r.y1), conv(r.x1, r.y0)]))

    if not texts and not doc["background"]:
        raise ParseError("The PDF page has no vector content — scanned drawings are not supported.")

    page_box = g.bbox_of_points([conv(0, 0), conv(page.rect.width, height)])
    max_symbol = 0.12 * max(page_box[2] - page_box[0], page_box[3] - page_box[1])

    def symbol_box(c):
        best = None
        for b in closed_boxes:
            w, h = g.bbox_size(b)
            if 0 < w <= max_symbol and 0 < h <= max_symbol and g.bbox_contains(b, c):
                if best is None or w * h < g.bbox_size(best)[0] * g.bbox_size(best)[1]:
                    best = b
        return best

    # split instrument bubbles: letters with the loop number just below
    used = set()
    tags: list[tuple[str, dict, list[float]]] = []
    for i, t in enumerate(texts):
        s = t["s"].strip()
        if i in used or not re.fullmatch(r"[A-Z]{2,4}", s) or not is_instrument_prefix(s):
            continue
        c = g.bbox_center(g.text_box(t))
        for j, u in enumerate(texts):
            if j in used or j == i or not re.fullmatch(r"\d{2,4}[A-Z]?", u["s"].strip()):
                continue
            cu = g.bbox_center(g.text_box(u))
            if abs(cu[0] - c[0]) < 1.5 * t["h"] and 0 < c[1] - cu[1] < 2.6 * t["h"]:
                used |= {i, j}
                tags.append((f"{s}-{u['s'].strip()}", t, [(c[0] + cu[0]) / 2, (c[1] + cu[1]) / 2]))
                break
    for i, t in enumerate(texts):
        if i not in used and looks_like_tag(t["s"]):
            used.add(i)
            tags.append((t["s"].strip(), t, g.bbox_center(g.text_box(t))))

    for tag, t, c in tags:
        m = LOOSE_TAG_RE.match(tag)
        type_ = prefix_type(m.group(1)) if m else None
        if not type_:
            continue
        box = symbol_box(c)
        ent = {"id": new_id(doc, "E"), "type": type_, "tag": tag, "block": None, "x": c[0], "y": c[1], "rot": 0.0,
               "sx": 1.0, "sy": 1.0, "layer": "PDF", "attrs": {},
               "label": {"dx": 0.0, "dy": 0.0, "h": t["h"], "rot": t.get("rot", 0), "style": "single"}}
        if box:
            ent["box"] = [box[0] - c[0], box[1] - c[1], box[2] - c[0], box[3] - c[1]]
        elif category(type_) == "equipment":
            # equipment tags usually sit under the symbol: assume a symbol-sized extent above the label
            h = t["h"]
            ent["box"] = [-5 * h, -h, 5 * h, 13 * h]
            ent["attrs"]["box_estimated"] = "true"
        doc["entities"].append(ent)

    used |= _title_block(doc, texts, used)
    doc["background"] += [t for i, t in enumerate(texts) if i not in used]
    recompute_bounds(doc)
    return doc


TITLE_LABELS = {"TITLE": "TITLE", "DWG NO": "DWG_NO", "DRAWING NO": "DWG_NO", "REV": "REV", "REVISION": "REV",
                "DRAWN": "DRAWN_BY", "DRAWN BY": "DRAWN_BY", "CHECKED": "CHECKED_BY", "CHECKED BY": "CHECKED_BY",
                "DATE": "DATE"}


def _title_block(doc: dict, texts: list[dict], used: set[int]) -> set[int]:
    """Recognise a title block from its field captions; each value is the text just below-right of a caption."""
    labels = {i: TITLE_LABELS[t["s"].strip().upper().rstrip(":")] for i, t in enumerate(texts)
              if i not in used and t["s"].strip().upper().rstrip(":") in TITLE_LABELS}
    if len(set(labels.values())) < 3:
        return set()
    region = g.bbox_expand(g.bbox_of(texts[i] for i in labels), 10 * max(texts[i]["h"] for i in labels))
    fields = {f: {"value": "", "p": texts[i]["p"], "h": texts[i]["h"]} for i, f in labels.items()}
    taken = set()
    for j, t in enumerate(texts):
        if j in used or j in labels or not g.bbox_contains(region, t["p"]):
            continue
        best, best_score = None, None
        for i, f in labels.items():
            lab = texts[i]
            dy, dx = lab["p"][1] - t["p"][1], t["p"][0] - lab["p"][0]
            if dy <= 0 or dx < -lab["h"] or dy > 6 * lab["h"]:
                continue
            score = dy + 0.3 * dx
            if best_score is None or score < best_score:
                best, best_score = f, score
        if best and not fields[best]["value"]:
            fields[best] = {"value": t["s"].strip(), "p": t["p"], "h": t["h"]}
            taken.add(j)
    doc["title_block"] = {"block": None, "x": region[0], "y": region[1], "sx": 1, "sy": 1, "rot": 0, "fields": fields}
    return taken
