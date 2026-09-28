"""Geometry primitives shared by parsers, rules, editors and exporters.

Primitives are plain dicts so they serialise straight into revision JSON:

  line   {"t": "line", "a": [x, y], "b": [x, y]}
  poly   {"t": "poly", "pts": [[x, y], ...], "closed": bool, "fill": bool}
  circle {"t": "circle", "c": [x, y], "r": r, "fill": bool}
  arc    {"t": "arc", "c": [x, y], "r": r, "a0": deg, "a1": deg}      # counter-clockwise a0 -> a1
  text   {"t": "text", "p": [x, y], "s": str, "h": height, "rot": deg,
          "ha": "left" | "center" | "right", "va": "baseline" | "middle" | "top"}

Any primitive may also carry "ls": "dashed" and "layer". Coordinates are y-up (CAD convention).
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

Point = Sequence[float]
BBox = list[float]  # [minx, miny, maxx, maxy]

TEXT_WIDTH_FACTOR = 0.62  # average glyph width / height for a monospace-ish CAD font


def dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def rotate(p: Point, deg: float) -> list[float]:
    if not deg:
        return [p[0], p[1]]
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return [p[0] * c - p[1] * s, p[0] * s + p[1] * c]


def transform_point(p: Point, x: float, y: float, rot: float = 0, sx: float = 1, sy: float = 1) -> list[float]:
    q = rotate([p[0] * sx, p[1] * sy], rot)
    return [q[0] + x, q[1] + y]


def transform_prim(prim: dict, x: float, y: float, rot: float = 0, sx: float = 1, sy: float = 1) -> dict:
    """Map a block-local primitive into world coordinates."""
    t = prim["t"]
    out = {k: v for k, v in prim.items()}
    tp = lambda p: transform_point(p, x, y, rot, sx, sy)  # noqa: E731
    if t == "line":
        out["a"], out["b"] = tp(prim["a"]), tp(prim["b"])
    elif t == "poly":
        out["pts"] = [tp(p) for p in prim["pts"]]
    elif t == "circle":
        out["c"], out["r"] = tp(prim["c"]), prim["r"] * abs(sx)
    elif t == "arc":
        a0, a1 = prim["a0"], prim["a1"]
        if sx * sy < 0:  # mirrored: arc direction flips
            a0, a1 = 180 - a1, 180 - a0
        out["c"], out["r"] = tp(prim["c"]), prim["r"] * abs(sx)
        out["a0"], out["a1"] = (a0 + rot) % 360, (a1 + rot) % 360
    elif t == "text":
        out["p"], out["h"] = tp(prim["p"]), prim["h"] * abs(sy)
        out["rot"] = (prim.get("rot", 0) + rot) % 360
    return out


def text_box(prim: dict) -> BBox:
    s, h = prim.get("s", ""), prim.get("h", 2.5)
    w = max(len(s), 1) * h * TEXT_WIDTH_FACTOR
    ha, va = prim.get("ha", "left"), prim.get("va", "baseline")
    x0 = {"left": 0, "center": -w / 2, "right": -w}[ha]
    y0 = {"baseline": 0, "middle": -h / 2, "top": -h}.get(va, 0)
    corners = [[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h]]
    pts = [transform_point(c, prim["p"][0], prim["p"][1], prim.get("rot", 0)) for c in corners]
    return bbox_of_points(pts)


def arc_points(c: Point, r: float, a0: float, a1: float, step_deg: float = 10) -> list[list[float]]:
    sweep = (a1 - a0) % 360 or 360
    n = max(2, int(math.ceil(sweep / step_deg)) + 1)
    return [
        [c[0] + r * math.cos(math.radians(a0 + sweep * i / (n - 1))),
         c[1] + r * math.sin(math.radians(a0 + sweep * i / (n - 1)))]
        for i in range(n)
    ]


def bbox_of_points(pts: Iterable[Point]) -> BBox:
    xs, ys = [], []
    for p in pts:
        xs.append(p[0])
        ys.append(p[1])
    if not xs:
        return [0.0, 0.0, 0.0, 0.0]
    return [min(xs), min(ys), max(xs), max(ys)]


def prim_bbox(prim: dict) -> BBox:
    t = prim["t"]
    if t == "line":
        return bbox_of_points([prim["a"], prim["b"]])
    if t == "poly":
        return bbox_of_points(prim["pts"])
    if t == "circle":
        (cx, cy), r = prim["c"], prim["r"]
        return [cx - r, cy - r, cx + r, cy + r]
    if t == "arc":
        return bbox_of_points(arc_points(prim["c"], prim["r"], prim["a0"], prim["a1"]))
    if t == "text":
        return text_box(prim)
    raise ValueError(f"unknown primitive {t}")


def bbox_of(prims: Iterable[dict]) -> BBox | None:
    box = None
    for p in prims:
        box = prim_bbox(p) if box is None else bbox_union(box, prim_bbox(p))
    return box


def bbox_union(a: BBox | None, b: BBox | None) -> BBox | None:
    if a is None:
        return b
    if b is None:
        return a
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def bbox_expand(b: BBox, d: float) -> BBox:
    return [b[0] - d, b[1] - d, b[2] + d, b[3] + d]


def bbox_center(b: BBox) -> list[float]:
    return [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2]


def bbox_size(b: BBox) -> tuple[float, float]:
    return b[2] - b[0], b[3] - b[1]


def bbox_contains(b: BBox, p: Point, tol: float = 0.0) -> bool:
    return b[0] - tol <= p[0] <= b[2] + tol and b[1] - tol <= p[1] <= b[3] + tol


def bbox_overlap_area(a: BBox, b: BBox) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def point_seg(p: Point, a: Point, b: Point) -> tuple[float, float, list[float]]:
    """Distance from p to segment ab, the segment parameter t in [0, 1], and the projection."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    ll = dx * dx + dy * dy
    t = 0.0 if ll == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / ll))
    q = [a[0] + t * dx, a[1] + t * dy]
    return dist(p, q), t, q


def point_polyline(p: Point, pts: Sequence[Point]) -> tuple[float, int, float, list[float]]:
    """Closest approach of p to a polyline: (distance, segment index, t, projection)."""
    best = (math.inf, 0, 0.0, [pts[0][0], pts[0][1]])
    for i in range(len(pts) - 1):
        d, t, q = point_seg(p, pts[i], pts[i + 1])
        if d < best[0]:
            best = (d, i, t, q)
    return best


def seg_bbox_clip(a: Point, b: Point, box: BBox) -> tuple[float, float] | None:
    """Liang-Barsky: parameter range [t0, t1] of segment ab inside box, or None."""
    t0, t1 = 0.0, 1.0
    dx, dy = b[0] - a[0], b[1] - a[1]
    for p, q in ((-dx, a[0] - box[0]), (dx, box[2] - a[0]), (-dy, a[1] - box[1]), (dy, box[3] - a[1])):
        if p == 0:
            if q < 0:
                return None
            continue
        r = q / p
        if p < 0:
            t0 = max(t0, r)
        else:
            t1 = min(t1, r)
        if t0 > t1:
            return None
    return t0, t1


def polyline_length(pts: Sequence[Point]) -> float:
    return sum(dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def point_along(pts: Sequence[Point], d: float) -> tuple[list[float], int]:
    """Point at arc-length d along a polyline and the index of the segment it lies on."""
    for i in range(len(pts) - 1):
        seg = dist(pts[i], pts[i + 1])
        if d <= seg or i == len(pts) - 2:
            t = 0 if seg == 0 else min(1.0, d / seg)
            a, b = pts[i], pts[i + 1]
            return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t], i
        d -= seg
    return [pts[-1][0], pts[-1][1]], len(pts) - 2


def simplify_polyline(pts: list[list[float]], eps: float = 1e-6) -> list[list[float]]:
    """Drop duplicate and collinear interior points."""
    out: list[list[float]] = []
    for p in pts:
        if out and dist(out[-1], p) <= eps:
            continue
        out.append([float(p[0]), float(p[1])])
    i = 1
    while i < len(out) - 1:
        a, b, c = out[i - 1], out[i], out[i + 1]
        cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        if abs(cross) <= eps * max(1.0, dist(a, c)):
            out.pop(i)
        else:
            i += 1
    return out


def orthogonal_route(a: Point, b: Point, horizontal_first: bool = True) -> list[list[float]]:
    """Manhattan route from a to b with at most two bends."""
    a, b = [float(a[0]), float(a[1])], [float(b[0]), float(b[1])]
    if abs(a[0] - b[0]) < 1e-9 or abs(a[1] - b[1]) < 1e-9:
        return [a, b]
    if horizontal_first:
        mx = (a[0] + b[0]) / 2
        return [a, [mx, a[1]], [mx, b[1]], b]
    my = (a[1] + b[1]) / 2
    return [a, [a[0], my], [b[0], my], b]


def cloud_points(box: BBox, arc_len: float) -> list[list[float]]:
    """Vertices spaced ~arc_len around a rectangle, counter-clockwise (for revision clouds)."""
    x0, y0, x1, y1 = box
    corners = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
    pts: list[list[float]] = []
    for i in range(4):
        a, b = corners[i], corners[i + 1]
        n = max(1, round(dist(a, b) / arc_len))
        for k in range(n):
            pts.append([a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n])
    return pts


def bulge_arc(p: Point, q: Point, bulge: float) -> tuple[list[float], float, float, float]:
    """Arc from p to q with a DXF bulge (> 0: counter-clockwise). Returns (centre, radius, a0, a1)
    such that the arc runs counter-clockwise from a0 to a1 when bulge > 0."""
    theta = 4 * math.atan(abs(bulge))
    chord = dist(p, q)
    r = chord / (2 * math.sin(theta / 2))
    d = (chord / 2) / math.tan(theta / 2)
    nx, ny = -(q[1] - p[1]) / chord, (q[0] - p[0]) / chord  # left normal of p -> q
    side = 1 if bulge > 0 else -1
    c = [(p[0] + q[0]) / 2 + side * nx * d, (p[1] + q[1]) / 2 + side * ny * d]
    a0 = math.degrees(math.atan2(p[1] - c[1], p[0] - c[0]))
    a1 = math.degrees(math.atan2(q[1] - c[1], q[0] - c[0]))
    return c, r, a0, a1
