import type { BBox, DrawingDoc, Entity, Line, Prim, Pt, Severity, TextPrim } from '../types';

export const SEVERITY_COLOR: Record<Severity, string> = {
  CRITICAL: '#f43f5e',
  HIGH: '#fb923c',
  MEDIUM: '#facc15',
  LOW: '#38bdf8',
};

export const TEXT_WIDTH = 0.62;
const CLOUD_BULGE = 0.55;

export function rotate(p: Pt, deg: number): Pt {
  if (!deg) return [p[0], p[1]];
  const r = (deg * Math.PI) / 180;
  const c = Math.cos(r);
  const s = Math.sin(r);
  return [p[0] * c - p[1] * s, p[0] * s + p[1] * c];
}

export function bboxOf(pts: Pt[]): BBox {
  let [x0, y0, x1, y1] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const [x, y] of pts) {
    x0 = Math.min(x0, x);
    y0 = Math.min(y0, y);
    x1 = Math.max(x1, x);
    y1 = Math.max(y1, y);
  }
  return [x0, y0, x1, y1];
}

export const union = (a: BBox | null, b: BBox | null): BBox | null =>
  !a ? b : !b ? a : [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[2], b[2]), Math.max(a[3], b[3])];
export const expand = (b: BBox, d: number): BBox => [b[0] - d, b[1] - d, b[2] + d, b[3] + d];
export const center = (b: BBox): Pt => [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2];

export function textBox(t: TextPrim): BBox {
  const w = Math.max(t.s.length, 1) * t.h * TEXT_WIDTH;
  const x0 = t.ha === 'center' ? -w / 2 : t.ha === 'right' ? -w : 0;
  const y0 = t.va === 'middle' ? -t.h / 2 : t.va === 'top' ? -t.h : 0;
  const corners: Pt[] = [[x0, y0], [x0 + w, y0], [x0 + w, y0 + t.h], [x0, y0 + t.h]];
  return bboxOf(corners.map((c) => {
    const q = rotate(c, t.rot ?? 0);
    return [q[0] + t.p[0], q[1] + t.p[1]] as Pt;
  }));
}

export function primBox(p: Prim): BBox {
  switch (p.t) {
    case 'line':
      return bboxOf([p.a, p.b]);
    case 'poly':
      return bboxOf(p.pts);
    case 'circle':
    case 'arc':
      return [p.c[0] - p.r, p.c[1] - p.r, p.c[0] + p.r, p.c[1] + p.r];
    case 'text':
      return textBox(p);
  }
}

const blockBoxes = new WeakMap<Prim[], BBox | null>();
export function blockBox(prims: Prim[] | undefined): BBox | null {
  if (!prims || !prims.length) return null;
  if (!blockBoxes.has(prims)) blockBoxes.set(prims, prims.map(primBox).reduce<BBox | null>(union, null));
  return blockBoxes.get(prims) ?? null;
}

export function entityBox(doc: DrawingDoc, e: Entity, dx = 0, dy = 0): BBox {
  const local = blockBox(doc.blocks[e.block ?? '']) ?? e.box ?? [-3, -3, 3, 3];
  const corners: Pt[] = [[local[0], local[1]], [local[2], local[1]], [local[2], local[3]], [local[0], local[3]]];
  return bboxOf(corners.map((c) => {
    const q = rotate([c[0] * e.sx, c[1] * e.sy], e.rot);
    return [q[0] + e.x + dx, q[1] + e.y + dy] as Pt;
  }));
}

export function lineTag(ln: Line, h = 2): TextPrim | null {
  if (!ln.tag) return null;
  if (ln.tag_pos) {
    const tp = ln.tag_pos;
    return { t: 'text', p: tp.p, s: ln.tag, h: tp.h ?? h, rot: tp.rot ?? 0,
      ha: (tp.ha as TextPrim['ha']) ?? 'left', va: (tp.va as TextPrim['va']) ?? 'baseline' };
  }
  let best = 0;
  let bestLen = -1;
  for (let i = 0; i < ln.pts.length - 1; i++) {
    const len = Math.hypot(ln.pts[i + 1][0] - ln.pts[i][0], ln.pts[i + 1][1] - ln.pts[i][1]);
    if (len > bestLen) [best, bestLen] = [i, len];
  }
  const [a, b] = [ln.pts[best], ln.pts[best + 1]];
  const mid: Pt = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  return Math.abs(a[0] - b[0]) >= Math.abs(a[1] - b[1])
    ? { t: 'text', p: [mid[0], mid[1] + 0.6 * h], s: ln.tag, h, rot: 0, ha: 'center', va: 'baseline' }
    : { t: 'text', p: [mid[0] - 0.6 * h, mid[1]], s: ln.tag, h, rot: 90, ha: 'center', va: 'baseline' };
}

const f = (n: number) => +n.toFixed(4);

export function arcPath(c: Pt, r: number, a0: number, a1: number): string {
  let sweep = (((a1 - a0) % 360) + 360) % 360;
  if (sweep === 0) sweep = 360;
  if (sweep >= 359.999) {
    return `M ${f(c[0] + r)} ${f(c[1])} A ${f(r)} ${f(r)} 0 1 1 ${f(c[0] - r)} ${f(c[1])} A ${f(r)} ${f(r)} 0 1 1 ${f(c[0] + r)} ${f(c[1])}`;
  }
  const s = (a0 * Math.PI) / 180;
  const e = ((a0 + sweep) * Math.PI) / 180;
  return `M ${f(c[0] + r * Math.cos(s))} ${f(c[1] + r * Math.sin(s))} A ${f(r)} ${f(r)} 0 ${sweep > 180 ? 1 : 0} 1 ${f(
    c[0] + r * Math.cos(e),
  )} ${f(c[1] + r * Math.sin(e))}`;
}

export function polyPath(pts: Pt[], closed = false): string {
  return pts.map((p, i) => `${i ? 'L' : 'M'} ${f(p[0])} ${f(p[1])}`).join(' ') + (closed ? ' Z' : '');
}

/** Revision-cloud outline: counter-clockwise around the box with outward bulging arcs. */
export function cloudPath(box: BBox, arcLen: number): string {
  const [x0, y0, x1, y1] = box;
  const corners: Pt[] = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]];
  const pts: Pt[] = [];
  for (let i = 0; i < 4; i++) {
    const [a, b] = [corners[i], corners[i + 1]];
    const n = Math.max(1, Math.round(Math.hypot(b[0] - a[0], b[1] - a[1]) / arcLen));
    for (let k = 0; k < n; k++) pts.push([a[0] + ((b[0] - a[0]) * k) / n, a[1] + ((b[1] - a[1]) * k) / n]);
  }
  const theta = 4 * Math.atan(CLOUD_BULGE);
  let d = `M ${f(pts[0][0])} ${f(pts[0][1])}`;
  for (let i = 0; i < pts.length; i++) {
    const [p, q] = [pts[i], pts[(i + 1) % pts.length]];
    const r = Math.hypot(q[0] - p[0], q[1] - p[1]) / (2 * Math.sin(theta / 2));
    d += ` A ${f(r)} ${f(r)} 0 0 1 ${f(q[0])} ${f(q[1])}`;
  }
  return d + ' Z';
}

/** Mirror of the backend's pipe-follow logic, used to preview drags before the server confirms. */
export function shiftLineEnd(pts: Pt[], end: 'start' | 'end', dx: number, dy: number): Pt[] {
  const out = pts.map((p) => [p[0], p[1]] as Pt);
  const [i, j] = end === 'start' ? [0, 1] : [out.length - 1, out.length - 2];
  const [p, q] = [out[i], out[j]];
  const horizontal = Math.abs(p[1] - q[1]) < 1e-6;
  const vertical = Math.abs(p[0] - q[0]) < 1e-6;
  const np: Pt = [p[0] + dx, p[1] + dy];
  if (out.length === 2) {
    out[i] = np;
    const [a, b] = out;
    if (horizontal && Math.abs(a[1] - b[1]) > 1e-6) {
      const mx = (a[0] + b[0]) / 2;
      return [a, [mx, a[1]], [mx, b[1]], b];
    }
    if (vertical && Math.abs(a[0] - b[0]) > 1e-6) {
      const my = (a[1] + b[1]) / 2;
      return [a, [a[0], my], [b[0], my], b];
    }
    return out;
  }
  if (horizontal) q[1] += dy;
  else if (vertical) q[0] += dx;
  out[i] = np;
  return out;
}

export function typeName(type: string): string {
  return type.replace(/_/g, ' ');
}
