import { useRef, useState } from 'react';
import { Cable, Link2, RotateCw, Trash2, X } from 'lucide-react';
import type { DrawingDoc, Issue } from '../types';
import type { Selection } from './DrawingCanvas';
import { typeName } from '../lib/draw';
import { Kbd } from './ui';

interface Props {
  doc: DrawingDoc;
  selection: Selection;
  issues: Issue[];
  busy: boolean;
  onRetag: (id: string, tag: string) => void;
  onRotate: (id: string) => void;
  onDelete: (id: string) => void;
  onConnect: (id: string, kind: 'process' | 'signal') => void;
  onSelectIssue: (key: string) => void;
  onClose: () => void;
}

export default function Inspector({ doc, selection, issues, busy, onRetag, onRotate, onDelete, onConnect, onSelectIssue, onClose }: Props) {
  const ent = selection.kind === 'entity' ? doc.entities.find((e) => e.id === selection.id) : undefined;
  const line = selection.kind === 'line' ? doc.lines.find((l) => l.id === selection.id) : undefined;
  const current = (ent?.tag ?? line?.tag) || '';
  const [tag, setTag] = useState(current);
  const [synced, setSynced] = useState(`${selection.id}|${current}`);
  if (synced !== `${selection.id}|${current}`) {
    setSynced(`${selection.id}|${current}`);
    setTag(current);
  }
  const input = useRef<HTMLInputElement>(null);

  if (!ent && !line) return null;
  const related = issues.filter((i) => i.status !== 'FIXED' && (i.entities.includes(selection.id) || i.lines.includes(selection.id)));
  const commit = () => {
    const v = tag.trim().toUpperCase();
    if (v && v !== current) onRetag(selection.id, v);
  };
  const length = line ? line.pts.slice(1).reduce((s, p, i) => s + Math.hypot(p[0] - line.pts[i][0], p[1] - line.pts[i][1]), 0) : 0;

  return (
    <div className="absolute top-3 left-3 z-20 w-72 rounded-xl border border-slate-700 bg-slate-900/95 shadow-2xl shadow-black/40 backdrop-blur"
      onPointerDown={(e) => e.stopPropagation()}>
      <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{ent ? typeName(ent.type) : `${line!.kind} line`}</div>
          <div className="font-mono text-xs text-slate-400">{selection.id}</div>
        </div>
        <button onClick={onClose} className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-white"><X className="h-4 w-4" /></button>
      </div>
      <div className="space-y-3 p-3">
        <label className="block">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{ent ? 'Tag' : 'Line number'}</span>
          <input ref={input} value={tag} onChange={(e) => setTag(e.target.value)} onBlur={commit}
            onKeyDown={(e) => { if (e.key === 'Enter') { commit(); input.current?.blur(); } }}
            placeholder={ent ? 'e.g. P-102' : 'e.g. 80-RW-1009'} disabled={busy}
            className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-sm text-white outline-none focus:border-blue-500" />
        </label>
        <div className="grid grid-cols-2 gap-2 font-mono text-[11px] text-slate-400">
          {ent ? (
            <>
              <span>x {ent.x.toFixed(1)}</span><span>y {ent.y.toFixed(1)}</span>
              <span>rot {ent.rot.toFixed(0)}°</span><span>{ent.block ?? 'text only'}</span>
            </>
          ) : (
            <><span>{line!.pts.length} points</span><span>{length.toFixed(1)} long</span></>
          )}
        </div>
        {related.length > 0 && (
          <div className="space-y-1">
            {related.map((i) => (
              <button key={i.key} onClick={() => onSelectIssue(i.key)}
                className="block w-full truncate rounded-md bg-rose-500/10 px-2 py-1 text-left text-[11px] text-rose-200 ring-1 ring-rose-500/20 hover:bg-rose-500/20">
                {i.rule_id} · {i.title}
              </button>
            ))}
          </div>
        )}
        <div className="flex flex-wrap gap-1.5">
          {ent && (
            <>
              <button disabled={busy} onClick={() => onRotate(ent.id)} title="Rotate 90° (R)"
                className="flex items-center gap-1 rounded-md bg-slate-800 px-2 py-1 text-xs text-slate-200 hover:bg-slate-700"><RotateCw className="h-3.5 w-3.5" /> Rotate</button>
              <button disabled={busy} onClick={() => onConnect(ent.id, 'process')} title="Draw a pipe to another component"
                className="flex items-center gap-1 rounded-md bg-slate-800 px-2 py-1 text-xs text-slate-200 hover:bg-slate-700"><Link2 className="h-3.5 w-3.5" /> Pipe to…</button>
              <button disabled={busy} onClick={() => onConnect(ent.id, 'signal')} title="Draw a signal line to another component"
                className="flex items-center gap-1 rounded-md bg-slate-800 px-2 py-1 text-xs text-slate-200 hover:bg-slate-700"><Cable className="h-3.5 w-3.5" /> Signal to…</button>
            </>
          )}
          <button disabled={busy} onClick={() => onDelete(selection.id)} title="Delete (Del)"
            className="flex items-center gap-1 rounded-md bg-rose-600/20 px-2 py-1 text-xs text-rose-200 ring-1 ring-rose-500/30 hover:bg-rose-600/30"><Trash2 className="h-3.5 w-3.5" /> Delete</button>
        </div>
        <p className="text-[10px] text-slate-500">Drag to move · <Kbd>R</Kbd> rotate · <Kbd>Del</Kbd> delete · <Kbd>Esc</Kbd> deselect</p>
      </div>
    </div>
  );
}
