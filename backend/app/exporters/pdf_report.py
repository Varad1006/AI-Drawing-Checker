"""PDF check report (ReportLab).

Page 1 is the drawing with revision clouds and numbered balloons; the following pages hold the
summary and the issue register with the checker's decisions. `drawing_pdf(doc)` renders just the
drawing (used to produce the sample vector PDF).
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import Flowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..core import geometry as g
from ..core.document import entity_world_prims, label_prim, line_tag_prim, title_block_prims

PAGE = landscape(A3)
INK = colors.HexColor("#1f2937")
SEVERITY_COLOURS = {"CRITICAL": "#dc2626", "HIGH": "#ea580c", "MEDIUM": "#ca8a04", "LOW": "#2563eb"}
STATUS_LABEL = {"OPEN": "Open", "ACCEPTED": "Accepted", "REJECTED": "Rejected", "FIXED": "Fixed"}


class _Painter:
    def __init__(self, c, bounds, frame):
        self.c = c
        fx, fy, fw, fh = frame
        bw, bh = max(bounds[2] - bounds[0], 1e-6), max(bounds[3] - bounds[1], 1e-6)
        self.s = min(fw / bw, fh / bh)
        self.ox = fx + (fw - bw * self.s) / 2 - bounds[0] * self.s
        self.oy = fy + (fh - bh * self.s) / 2 - bounds[1] * self.s

    def pt(self, p):
        return self.ox + p[0] * self.s, self.oy + p[1] * self.s

    def prim(self, p, width=0.5, colour=INK):
        c = self.c
        c.setStrokeColor(colour)
        c.setFillColor(colour)
        c.setLineWidth(width)
        c.setDash(3, 2) if p.get("ls") == "dashed" else c.setDash()
        t = p["t"]
        if t == "line":
            (x1, y1), (x2, y2) = self.pt(p["a"]), self.pt(p["b"])
            c.line(x1, y1, x2, y2)
        elif t == "poly":
            path = c.beginPath()
            path.moveTo(*self.pt(p["pts"][0]))
            for q in p["pts"][1:]:
                path.lineTo(*self.pt(q))
            if p.get("closed"):
                path.close()
            c.drawPath(path, stroke=1, fill=1 if p.get("fill") else 0)
        elif t == "circle":
            x, y = self.pt(p["c"])
            c.circle(x, y, p["r"] * self.s, stroke=1, fill=1 if p.get("fill") else 0)
        elif t == "arc":
            x, y = self.pt(p["c"])
            r = p["r"] * self.s
            c.arc(x - r, y - r, x + r, y + r, p["a0"], (p["a1"] - p["a0"]) % 360 or 360)
        elif t == "text":
            self.text(p["s"], p["p"], p.get("h", 2.5), p.get("rot", 0), p.get("ha", "left"), p.get("va", "baseline"), colour)

    def text(self, s, p, h, rot=0, ha="left", va="baseline", colour=INK, bold=False):
        c = self.c
        size = max(h * self.s / 0.72, 1.0)
        x, y = self.pt(p)
        c.saveState()
        c.setFillColor(colour)
        c.translate(x, y)
        c.rotate(rot)
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        dy = {"middle": -0.36 * size, "top": -0.72 * size}.get(va, 0)
        {"center": c.drawCentredString, "right": c.drawRightString}.get(ha, c.drawString)(0, dy, s)
        c.restoreState()

    def cloud(self, box, colour, arc_len):
        c = self.c
        c.setStrokeColor(colour)
        c.setLineWidth(1.1)
        c.setDash()
        pts = g.cloud_points(box, arc_len)
        for p, q in zip(pts, pts[1:] + pts[:1]):
            centre, r, a0, a1 = g.bulge_arc(p, q, 0.55)
            x, y = self.pt(centre)
            rr = r * self.s
            c.arc(x - rr, y - rr, x + rr, y + rr, a0, (a1 - a0) % 360)


def render_drawing(c, doc: dict, frame, issues: list[dict] | None = None) -> None:
    bounds = list(doc["bounds"])
    for iss in issues or []:
        if iss.get("bbox"):
            bounds = g.bbox_union(bounds, g.bbox_expand(iss["bbox"], 8))
    p = _Painter(c, bounds, frame)
    for prim in doc["background"]:
        p.prim(prim, 0.35, colors.HexColor("#4b5563"))
    for prim in title_block_prims(doc):
        p.prim(prim, 0.5)
    for ln in doc["lines"]:
        dashed = ln.get("kind") == "signal"
        p.prim({"t": "poly", "pts": ln["pts"], "closed": False, "ls": "dashed" if dashed else None},
               0.5 if dashed else 0.9)
        tag = line_tag_prim(ln)
        if tag:
            p.prim(tag, colour=colors.HexColor("#374151"))
    for e in doc["entities"]:
        for prim in entity_world_prims(doc, e):
            p.prim(prim, 0.7)
        lab = label_prim(e)
        if lab and (e.get("label") or {}).get("style") == "split" and "-" in e["tag"]:
            letters, number = e["tag"].split("-", 1)
            h = lab["h"] * 0.95
            p.text(letters, [lab["p"][0], lab["p"][1] + h * 0.15], h, 0, "center", "baseline")
            p.text(number, [lab["p"][0], lab["p"][1] - h * 0.15], h, 0, "center", "top")
        elif lab:
            p.prim(lab)
    arc_len = max(bounds[2] - bounds[0], bounds[3] - bounds[1]) / 110
    for n, iss in enumerate(issues or [], 1):
        if not iss.get("bbox"):
            continue
        colour = colors.HexColor(SEVERITY_COLOURS.get(iss["severity"], "#dc2626"))
        box = g.bbox_expand(iss["bbox"], arc_len * 0.8)
        p.cloud(box, colour, arc_len)
        bx, by = box[0], box[3]
        c.setFillColor(colour)
        x, y = p.pt([bx, by])
        c.circle(x, y, 2.6 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 7)
        c.drawCentredString(x, y - 2.4, str(n))


class _DrawingFlowable(Flowable):
    def __init__(self, doc, issues, width, height):
        super().__init__()
        self.doc, self.issues, self.width, self.height = doc, issues, width, height

    def wrap(self, *_):
        return self.width, self.height

    def draw(self):
        self.canv.setStrokeColor(colors.HexColor("#d1d5db"))
        self.canv.rect(0, 0, self.width, self.height)
        render_drawing(self.canv, self.doc, (6 * mm, 6 * mm, self.width - 12 * mm, self.height - 12 * mm), self.issues)


def report_pdf(doc: dict, issues: list[dict], meta: dict) -> bytes:
    """meta: filename, revision, revisions, stats {open, accepted, rejected, fixed}, ai_model."""
    buf = io.BytesIO()
    margin = 14 * mm
    pdf = SimpleDocTemplate(buf, pagesize=PAGE, leftMargin=margin, rightMargin=margin, topMargin=24 * mm,
                            bottomMargin=16 * mm, title=f"Check report — {meta.get('filename', '')}",
                            author="Lead Checker")
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=8.5, leading=11, textColor=INK)
    small = ParagraphStyle("small", parent=body, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#4b5563"))
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=13, textColor=INK, spaceAfter=6)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def chrome(c, d):
        c.saveState()
        w, h = PAGE
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(margin, h - 14 * mm, "DRAWING CHECK REPORT")
        c.setFont("Helvetica", 9)
        c.setFillColor(colors.HexColor("#4b5563"))
        c.drawString(margin + c.stringWidth("DRAWING CHECK REPORT", "Helvetica-Bold", 14) + 6 * mm, h - 14 * mm,
                     f"{meta.get('filename', '')}   ·   revision {meta.get('revision', 1)} of {meta.get('revisions', 1)}")
        c.drawRightString(w - margin, h - 14 * mm, f"Generated {generated}")
        c.setStrokeColor(colors.HexColor("#d1d5db"))
        c.line(margin, h - 17 * mm, w - margin, h - 17 * mm)
        c.setFont("Helvetica", 8)
        c.drawString(margin, 9 * mm, "Lead Checker — deterministic rule engine" +
                     (f" + AI review ({meta['ai_model']})" if meta.get("ai_model") else ""))
        c.drawRightString(w - margin, 9 * mm, f"Page {d.page}")
        c.restoreState()

    story: list = []
    width, height = PAGE[0] - 2 * margin - 12, PAGE[1] - 40 * mm - 12  # frame has 6pt padding each side
    story.append(_DrawingFlowable(doc, issues, width, height))
    story.append(PageBreak())

    stats = meta.get("stats", {})
    story.append(Paragraph("Summary", h2))
    sev_counts = {s: sum(1 for i in issues if i["severity"] == s and i.get("status") != "FIXED")
                  for s in SEVERITY_COLOURS}
    summary = [["Open", "Accepted", "Rejected", "Fixed during check", "Critical", "High", "Medium", "Low"],
               [stats.get("open", 0), stats.get("accepted", 0), stats.get("rejected", 0), stats.get("fixed", 0),
                *sev_counts.values()]]
    t = Table(summary, hAlign="LEFT", colWidths=[32 * mm] * 8)
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8), ("FONT", (0, 1), (-1, 1), "Helvetica-Bold", 14),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
        ("TOPPADDING", (0, 1), (-1, 1), 6), ("BOTTOMPADDING", (0, 1), (-1, 1), 6),
    ]))
    story += [t, Spacer(1, 8 * mm), Paragraph("Issue register", h2)]

    rows = [["#", "Severity", "Rule", "Finding", "Recommendation", "Status / comment"]]
    for n, iss in enumerate(issues, 1):
        status = STATUS_LABEL.get(iss.get("status", "OPEN"), iss.get("status", ""))
        comment = iss.get("comment") or ""
        source = "AI review" if iss.get("source") == "ai" else "Rule"
        rows.append([
            str(n),
            Paragraph(f'<font color="{SEVERITY_COLOURS.get(iss["severity"], "#000")}"><b>{iss["severity"]}</b></font>', body),
            Paragraph(f"{iss['rule_id']}<br/><font size=7 color='#6b7280'>{source}</font>", body),
            Paragraph(f"<b>{_esc(iss['title'])}</b><br/>{_esc(iss['description'])}", body),
            Paragraph(_esc(iss.get("recommendation") or ""), body),
            Paragraph(f"<b>{status}</b>" + (f"<br/>{_esc(comment)}" if comment else ""), small),
        ])
    if len(rows) == 1:
        rows.append(["", "", "", Paragraph("No findings — the drawing passed every check.", body), "", ""])
    reg = Table(rows, repeatRows=1, hAlign="LEFT",
                colWidths=[9 * mm, 22 * mm, 22 * mm, 150 * mm, 110 * mm, width - 313 * mm])
    reg.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8), ("TEXTCOLOR", (0, 0), (-1, 0), INK),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONT", (0, 1), (0, -1), "Helvetica-Bold", 8),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#e5e7eb")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(reg)
    pdf.build(story, onFirstPage=chrome, onLaterPages=chrome)
    return buf.getvalue()


def drawing_pdf(doc: dict) -> bytes:
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=PAGE)
    b = doc["bounds"]
    s = min(PAGE[0] / (b[2] - b[0]), PAGE[1] / (b[3] - b[1]))
    render_drawing(c, doc, (0, 0, (b[2] - b[0]) * s, (b[3] - b[1]) * s))
    c.showPage()
    c.save()
    return buf.getvalue()


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
