import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { BBox, DrawingDoc, Entity, Issue, Line, Prim, Pt, TextPrim } from '../types';
import {
  SEVERITY_COLOR, arcPath, center, cloudPath, entityBox, expand, lineTag, polyPath, shiftLineEnd, union,
} from '../lib/draw';

export type Selection = { kind: 'entity' | 'line'; id: string };
export type Mode = { kind: 'select' } | { kind: 'place'; type: string } | { kind: 'connect'; from: string };

interface Props {
  doc: DrawingDoc;
  attachments: Record<string, [string, 'start' | 'end'][]>;
  issues: Issue[];
  selectedIssue: string | null;
  selection: Selection | null;
  changed: Set<string>;
  mode: Mode;
  focus: { box: BBox; nonce: number } | null;
  onSelect: (sel: Selection | null) => void;
  onSelectIssue: (key: string | null) => void;
  onMove: (id: string, x: number, y: number) => void;
  onPlace: (p: Pt) => void;
  onConnect: (target: string) => void;
}

type VB = { x: number; y: number; w: number; h: number };
type Drag =
  | { kind: 'pan'; sx: number; sy: number; vb: VB; moved: boolean; button: number }
  | { kind: 'entity'; id: string; start: Pt; moved: boolean };

const INK = '#d7dee9';
const MUTED = '#6b7a90';
const ACCENT = '#60a5fa';
const CHANGED = '#34d399';

function TextEl({ t, color, weight }: { t: TextPrim; color: string; weight?: number }) {
  const anchor = t.ha === 'center' ? 'middle' : t.ha === 'right' ? 'end' : 'start';
  const baseline = t.va === 'middle' ? 'central' : t.va === 'top' ? 'hanging' : 'alphabetic';
  return (
    <text
      transform={`translate(${t.p[0]} ${t.p[1]}) rotate(${t.rot ?? 0}) scale(1 -1)`}
      fontSize={t.h / 0.72}
      textAnchor={anchor}
      dominantBaseline={baseline}
      fill={color}
      fontWeight={weight}
      className="cad-text"
    >
      {t.s}
    </text>
  );
}

function PrimEl({ p, color }: { p: Prim; color?: string }) {
  const stroke = color ?? 'currentColor';
  const dash = p.ls === 'dashed' ? '4 3' : undefined;
  const common = { stroke, strokeDasharray: dash, vectorEffect: 'non-scaling-stroke' as const };
  switch (p.t) {
    case 'line':
      return <line x1={p.a[0]} y1={p.a[1]} x2={p.b[0]} y2={p.b[1]} {...common} />;
    case 'poly':
      return <path d={polyPath(p.pts, p.closed)} fill={p.fill ? stroke : 'none'} {...common} />;
    case 'circle':
      return <circle cx={p.c[0]} cy={p.c[1]} r={p.r} fill={p.fill ? stroke : 'none'} {...common} />;
    case 'arc':
      return <path d={arcPath(p.c, p.r, p.a0, p.a1)} fill="none" {...common} />;
    case 'text':
      return <TextEl t={p} color={color ?? 'currentColor'} />;
  }
}

const Blocks = memo(function Blocks({ blocks }: { blocks: Record<string, Prim[]> }) {
  return (
    <defs>
      {Object.entries(blocks).map(([name, prims]) => (
        <g id={`blk-${name}`} key={name}>
          {prims.map((p, i) => <PrimEl key={i} p={p} />)}
        </g>
      ))}
      <pattern id="grid-minor" width="10" height="10" patternUnits="userSpaceOnUse">
        <path d="M 10 0 L 0 0 0 10" fill="none" stroke="#18212f" strokeWidth="1" vectorEffect="non-scaling-stroke" />
      </pattern>
      <pattern id="grid-major" width="50" height="50" patternUnits="userSpaceOnUse">
        <rect width="50" height="50" fill="url(#grid-minor)" />
        <path d="M 50 0 L 0 0 0 50" fill="none" stroke="#1f2b3d" strokeWidth="1" vectorEffect="non-scaling-stroke" />
      </pattern>
    </defs>
  );
});

const Background = memo(function Background({ doc }: { doc: DrawingDoc }) {
  const tb = doc.title_block;
  return (
    <g color={MUTED} strokeWidth={1}>
      {doc.background.map((p, i) => <PrimEl key={i} p={p} />)}
      {tb?.block && doc.blocks[tb.block] && (
        <use href={`#blk-${tb.block}`} transform={`translate(${tb.x} ${tb.y}) rotate(${tb.rot}) scale(${tb.sx} ${tb.sy})`} />
      )}
      {tb && Object.values(tb.fields).filter((fl) => fl.value).map((fl, i) => (
        <TextEl key={i} t={{ t: 'text', p: fl.p, s: fl.value, h: fl.h, ha: 'left', va: 'baseline' }} color={INK} />
      ))}
    </g>
  );
});

function EntityLabel({ e, color }: { e: Entity; color: string }) {
  if (!e.tag || !e.label) return null;
  const p: Pt = [e.x + e.label.dx, e.y + e.label.dy];
  if (e.label.style === 'split' && e.tag.includes('-')) {
    const [letters, number] = e.tag.split('-', 2);
    const h = e.label.h * 1.15;
    return (
      <g>
        <TextEl t={{ t: 'text', p: [p[0], p[1] + h * 0.15], s: letters, h, ha: 'center', va: 'baseline' }} color={color} weight={600} />
        <TextEl t={{ t: 'text', p: [p[0], p[1] - h * 0.15], s: number, h, ha: 'center', va: 'top' }} color={color} weight={600} />
      </g>
    );
  }
  return <TextEl t={{ t: 'text', p, s: e.tag, h: e.label.h, rot: e.label.rot, ha: 'center', va: 'middle' }} color={color} weight={600} />;
}

export default function DrawingCanvas(props: Props) {
  const { doc, attachments, issues, selectedIssue, selection, changed, mode, focus } = props;
  const wrapRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 800, h: 600 });
  const [vb, setVb] = useState<VB>({ x: 0, y: -300, w: 420, h: 300 });
  const [drag, setDrag] = useState<Drag | null>(null);
  const [offset, setOffset] = useState<{ id: string; dx: number; dy: number } | null>(null);
  const [cursor, setCursor] = useState<Pt | null>(null);
  const fitted = useRef(false);

  const fit = useCallback(
    (box: BBox, pad = 0.06) => {
      const w0 = box[2] - box[0];
      const h0 = box[3] - box[1];
      const padded = expand(box, Math.max(w0, h0) * pad);
      let w = padded[2] - padded[0];
      let h = padded[3] - padded[1];
      const aspect = size.w / size.h;
      if (w / h > aspect) h = w / aspect;
      else w = h * aspect;
      const [cx, cy] = center(padded);
      setVb({ x: cx - w / 2, y: -cy - h / 2, w, h });
    },
    [size],
  );

  useLayoutEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      if (width > 0 && height > 0) setSize({ w: width, h: height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // keep the view box aspect equal to the element so screen <-> world mapping stays uniform
  useEffect(() => {
    if (!fitted.current && size.w > 0) {
      fitted.current = true;
      fit(doc.bounds);
      return;
    }
    setVb((v) => {
      const h = v.w * (size.h / size.w);
      return { x: v.x, y: v.y + (v.h - h) / 2, w: v.w, h };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [size]);

  useEffect(() => {
    if (focus) fit(focus.box, 0.9);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus?.nonce]);

  // a new document (after the server confirms a move) replaces the local drag preview
  const [offsetDoc, setOffsetDoc] = useState(doc);
  if (offsetDoc !== doc) {
    setOffsetDoc(doc);
    setOffset(null);
  }

  const toWorld = useCallback(
    (cx: number, cy: number): Pt => {
      const r = wrapRef.current!.getBoundingClientRect();
      return [vb.x + ((cx - r.left) / r.width) * vb.w, -(vb.y + ((cy - r.top) / r.height) * vb.h)];
    },
    [vb],
  );

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const onWheel = (ev: WheelEvent) => {
      ev.preventDefault();
      const r = el.getBoundingClientRect();
      const factor = Math.exp(ev.deltaY * (ev.ctrlKey ? 0.01 : 0.0015));
      setVb((v) => {
        const w = Math.min(Math.max(v.w * factor, 5), 20000);
        const k = w / v.w;
        const mx = v.x + ((ev.clientX - r.left) / r.width) * v.w;
        const my = v.y + ((ev.clientY - r.top) / r.height) * v.h;
        return { x: mx - (mx - v.x) * k, y: my - (my - v.y) * k, w, h: v.h * k };
      });
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, []);

  const pxToWorld = vb.w / size.w;
  const bw = doc.bounds[2] - doc.bounds[0];
  const bh = doc.bounds[3] - doc.bounds[1];
  const fitWidth = Math.max(bw, bh * (size.w / size.h)) * 1.12;  // view width at "fit" (100%)

  const onPointerDown = (ev: React.PointerEvent) => {
    wrapRef.current?.setPointerCapture(ev.pointerId);
    setDrag({ kind: 'pan', sx: ev.clientX, sy: ev.clientY, vb, moved: false, button: ev.button });
  };

  const onEntityDown = (ev: React.PointerEvent, e: Entity) => {
    if (ev.button !== 0) return;
    ev.stopPropagation();
    if (mode.kind === 'connect') {
      props.onConnect(e.id);
      return;
    }
    if (mode.kind === 'place') return;
    props.onSelect({ kind: 'entity', id: e.id });
    wrapRef.current?.setPointerCapture(ev.pointerId);
    setDrag({ kind: 'entity', id: e.id, start: toWorld(ev.clientX, ev.clientY), moved: false });
  };

  const onLineDown = (ev: React.PointerEvent, ln: Line) => {
    if (ev.button !== 0 || mode.kind !== 'select') return;
    ev.stopPropagation();
    props.onSelect({ kind: 'line', id: ln.id });
  };

  const onPointerMove = (ev: React.PointerEvent) => {
    const w = toWorld(ev.clientX, ev.clientY);
    setCursor(w);
    if (!drag) return;
    if (drag.kind === 'pan') {
      const r = wrapRef.current!.getBoundingClientRect();
      const dx = ev.clientX - drag.sx;
      const dy = ev.clientY - drag.sy;
      if (Math.abs(dx) + Math.abs(dy) > 3) {
        setVb({ ...drag.vb, x: drag.vb.x - (dx / r.width) * drag.vb.w, y: drag.vb.y - (dy / r.height) * drag.vb.h });
        if (!drag.moved) setDrag({ ...drag, moved: true });
      }
    } else {
      const dx = w[0] - drag.start[0];
      const dy = w[1] - drag.start[1];
      if (drag.moved || Math.hypot(dx, dy) / pxToWorld > 3) {
        if (!drag.moved) setDrag({ ...drag, moved: true });
        setOffset({ id: drag.id, dx, dy });
      }
    }
  };

  const onPointerUp = (ev: React.PointerEvent) => {
    if (!drag) return;
    if (drag.kind === 'pan' && !drag.moved && drag.button === 0) {
      if (mode.kind === 'place') props.onPlace(toWorld(ev.clientX, ev.clientY));
      else if (mode.kind === 'select') {
        props.onSelect(null);
        props.onSelectIssue(null);
      }
    }
    if (drag.kind === 'entity' && drag.moved && offset) {
      const e = doc.entities.find((x) => x.id === drag.id);
      if (e) props.onMove(e.id, +(e.x + offset.dx).toFixed(3), +(e.y + offset.dy).toFixed(3));
      else setOffset(null);
    }
    setDrag(null);
  };

  // ---------------------------------------------------------------------------------------------

  const selIssue = issues.find((i) => i.key === selectedIssue) ?? null;
  const issueEntities = new Set(selIssue?.entities ?? []);
  const issueLines = new Set(selIssue?.lines ?? []);
  const issueColor = selIssue ? SEVERITY_COLOR[selIssue.severity] : ACCENT;

  const previewLines = useMemo(() => {
    if (!offset) return null;
    const map = new Map<string, Pt[]>();
    for (const [lid, end] of attachments[offset.id] ?? []) {
      const ln = doc.lines.find((l) => l.id === lid);
      if (ln) map.set(lid, shiftLineEnd(map.get(lid) ?? ln.pts, end, offset.dx, offset.dy));
    }
    return map;
  }, [offset, attachments, doc.lines]);

  const lineColor = (ln: Line) =>
    selection?.kind === 'line' && selection.id === ln.id ? ACCENT
      : issueLines.has(ln.id) ? issueColor
      : changed.has(ln.id) ? CHANGED
      : ln.kind === 'signal' ? '#8b9ab0' : INK;

  const entityColor = (e: Entity) =>
    selection?.kind === 'entity' && selection.id === e.id ? ACCENT
      : mode.kind === 'connect' && mode.from === e.id ? ACCENT
      : issueEntities.has(e.id) ? issueColor
      : changed.has(e.id) ? CHANGED
      : INK;

  const selectedBox = selection?.kind === 'entity'
    ? (() => {
        const e = doc.entities.find((x) => x.id === selection.id);
        return e ? entityBox(doc, e, offset?.id === e.id ? offset.dx : 0, offset?.id === e.id ? offset.dy : 0) : null;
      })()
    : null;

  const arcLen = Math.max(doc.bounds[2] - doc.bounds[0], doc.bounds[3] - doc.bounds[1]) / 110;
  const worldBox: BBox = [vb.x, -(vb.y + vb.h), vb.x + vb.w, -vb.y];
  const cursorClass = drag?.kind === 'pan' && drag.moved ? 'cursor-grabbing'
    : mode.kind === 'place' ? 'cursor-crosshair' : mode.kind === 'connect' ? 'cursor-cell' : 'cursor-default';

  return (
    <div
      ref={wrapRef}
      className={`absolute inset-0 select-none touch-none ${cursorClass}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerLeave={() => setCursor(null)}
      onDoubleClick={(ev) => {
        if (ev.target === ev.currentTarget || (ev.target as Element).tagName === 'svg') fit(doc.bounds);
      }}
    >
      <svg width="100%" height="100%" viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`} className="block">
        <Blocks blocks={doc.blocks} />
        <g transform="scale(1 -1)">
          <rect x={worldBox[0]} y={worldBox[1]} width={vb.w} height={vb.h} fill="url(#grid-major)" />
          <Background doc={doc} />

          {doc.lines.map((ln) => {
            const pts = previewLines?.get(ln.id) ?? ln.pts;
            const color = lineColor(ln);
            const tag = lineTag({ ...ln, pts, tag_pos: previewLines?.has(ln.id) ? null : ln.tag_pos });
            const emphasised = color !== INK && color !== '#8b9ab0';
            return (
              <g key={ln.id} className={changed.has(ln.id) ? 'animate-changed' : undefined}>
                <path d={polyPath(pts)} fill="none" stroke="transparent" strokeWidth={10}
                  vectorEffect="non-scaling-stroke" onPointerDown={(ev) => onLineDown(ev, ln)}
                  className={mode.kind === 'select' ? 'cursor-pointer' : undefined} />
                <path d={polyPath(pts)} fill="none" stroke={color} strokeWidth={emphasised ? 2.2 : ln.kind === 'signal' ? 1 : 1.5}
                  strokeDasharray={ln.kind === 'signal' ? '5 4' : undefined} vectorEffect="non-scaling-stroke" pointerEvents="none" />
                {tag && <g pointerEvents="none"><TextEl t={tag} color={emphasised ? color : '#9aa8bb'} /></g>}
              </g>
            );
          })}

          {doc.entities.map((e) => {
            const color = entityColor(e);
            const o = offset?.id === e.id ? offset : null;
            const ex = e.x + (o?.dx ?? 0);
            const ey = e.y + (o?.dy ?? 0);
            const hasBlock = !!(e.block && doc.blocks[e.block]);
            return (
              <g key={e.id} color={color} strokeWidth={color === INK ? 1.4 : 2.2}
                className={`${changed.has(e.id) ? 'animate-changed' : ''} ${mode.kind === 'place' ? '' : 'cursor-pointer'}`}
                onPointerDown={(ev) => onEntityDown(ev, e)}>
                <title>{`${e.tag ?? 'untagged'} — ${e.type.replace(/_/g, ' ')} (${e.id})`}</title>
                {(() => {
                  const box = entityBox(doc, e, o?.dx ?? 0, o?.dy ?? 0);
                  return <rect x={box[0]} y={box[1]} width={box[2] - box[0]} height={box[3] - box[1]} fill="transparent" />;
                })()}
                {hasBlock ? (
                  <use href={`#blk-${e.block}`} transform={`translate(${ex} ${ey}) rotate(${e.rot}) scale(${e.sx} ${e.sy})`} />
                ) : null}
                <EntityLabel e={{ ...e, x: ex, y: ey }} color={color === INK ? '#e8eef7' : color} />
              </g>
            );
          })}

          {selectedBox && (
            <rect x={selectedBox[0] - 1.5} y={selectedBox[1] - 1.5} width={selectedBox[2] - selectedBox[0] + 3}
              height={selectedBox[3] - selectedBox[1] + 3} fill="none" stroke={ACCENT} strokeDasharray="4 3"
              vectorEffect="non-scaling-stroke" pointerEvents="none" />
          )}

          {issues.map((iss, n) => {
            if (!iss.bbox) return null;
            const active = iss.key === selectedIssue;
            const color = SEVERITY_COLOR[iss.severity];
            const box = expand(iss.bbox, arcLen * 0.8);
            const r = 9 * pxToWorld;
            return (
              <g key={iss.key} opacity={selectedIssue && !active ? 0.35 : 1}>
                <path d={cloudPath(box, arcLen)} fill={color} fillOpacity={active ? 0.1 : 0.04} stroke={color}
                  strokeWidth={active ? 2.2 : 1.4} vectorEffect="non-scaling-stroke" pointerEvents="none"
                  className={active ? 'animate-cloud' : undefined} />
                <g className="cursor-pointer" onPointerDown={(ev) => { ev.stopPropagation(); props.onSelectIssue(iss.key); }}>
                  <circle cx={box[0]} cy={box[3]} r={r} fill={color} stroke="#0b1220" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
                  <TextEl t={{ t: 'text', p: [box[0], box[3]], s: String(n + 1), h: r * 0.95, ha: 'center', va: 'middle' }}
                    color="#0b1220" weight={700} />
                </g>
              </g>
            );
          })}
        </g>
      </svg>

      <div className="pointer-events-none absolute bottom-3 left-3 flex gap-2 font-mono text-[11px] text-slate-500">
        {cursor && <span className="rounded bg-slate-900/80 px-2 py-1">x {cursor[0].toFixed(1)} · y {cursor[1].toFixed(1)}</span>}
        <span className="rounded bg-slate-900/80 px-2 py-1">{Math.round((fitWidth / vb.w) * 100)}%</span>
      </div>

      <div className="absolute right-3 bottom-3 flex flex-col overflow-hidden rounded-lg border border-slate-700/80 bg-slate-900/90 shadow-lg"
        onPointerDown={(ev) => ev.stopPropagation()}>
        {[
          { label: '+', title: 'Zoom in', k: 0.7 },
          { label: '−', title: 'Zoom out', k: 1 / 0.7 },
        ].map((b) => (
          <button key={b.label} title={b.title} className="h-8 w-8 text-lg text-slate-300 hover:bg-slate-800 hover:text-white"
            onClick={() => setVb((v) => ({ x: v.x + (v.w * (1 - b.k)) / 2, y: v.y + (v.h * (1 - b.k)) / 2, w: v.w * b.k, h: v.h * b.k }))}>
            {b.label}
          </button>
        ))}
        <button title="Fit drawing (F)" className="h-8 w-8 border-t border-slate-700 text-[10px] font-bold text-slate-300 hover:bg-slate-800 hover:text-white"
          onClick={() => fit(union(doc.bounds, null)!)}>
          FIT
        </button>
      </div>
    </div>
  );
}
