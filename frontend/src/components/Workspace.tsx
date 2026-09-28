import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowLeft, Bot, ChevronDown, CircleCheck, Download, FileCode2, FileDown, FileText, History, ListChecks, Loader2,
  MessageSquareText, Plus, Redo2, Sparkles, TriangleAlert, Undo2, User, Wand2, Workflow,
} from 'lucide-react';
import { api, errorMessage } from '../api';
import type { BBox, ChatMessage, ComponentType, Detail, Op, Pt, RevisionInfo } from '../types';
import { entityBox, expand, typeName } from '../lib/draw';
import { toast } from '../lib/toast';
import DrawingCanvas, { type Mode, type Selection } from './DrawingCanvas';
import IssuePanel from './IssuePanel';
import ChatPanel from './ChatPanel';
import Inspector from './Inspector';
import { Kbd, Menu, MenuItem } from './ui';

const AUTHOR_ICON: Record<RevisionInfo['author'], { icon: typeof User; label: string; cls: string }> = {
  import: { icon: FileDown, label: 'Imported', cls: 'text-slate-400' },
  user: { icon: User, label: 'You', cls: 'text-blue-300' },
  'auto-fix': { icon: Wand2, label: 'Auto-fix', cls: 'text-emerald-300' },
  ai: { icon: Sparkles, label: 'AI assistant', cls: 'text-violet-300' },
  assistant: { icon: Bot, label: 'Assistant', cls: 'text-violet-300' },
};

function timeAgo(iso: string) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}

export default function Workspace({ id, onBack }: { id: number; onBack: () => void }) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [chat, setChat] = useState<ChatMessage[]>([]);
  const [types, setTypes] = useState<ComponentType[]>([]);
  const [tab, setTab] = useState<'issues' | 'chat'>('issues');
  const [selection, setSelection] = useState<Selection | null>(null);
  const [selectedIssue, setSelectedIssue] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode & { line?: 'process' | 'signal' }>({ kind: 'select' });
  const [focus, setFocus] = useState<{ box: BBox; nonce: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [chatBusy, setChatBusy] = useState(false);
  const [flash, setFlash] = useState<Set<string>>(new Set());
  const [loadError, setLoadError] = useState<string | null>(null);
  const flashTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const receive = useCallback((d: Detail, highlight = true) => {
    setDetail(d);
    if (d.chat) setChat(d.chat);
    if (highlight && d.changed.length) {
      setFlash(new Set(d.changed));
      if (flashTimer.current) clearTimeout(flashTimer.current);
      flashTimer.current = setTimeout(() => setFlash(new Set()), 4500);
    }
  }, []);

  useEffect(() => {
    let alive = true;
    Promise.all([api.get(id), api.chat(id), api.rules()])
      .then(([d, c, r]) => {
        if (!alive) return;
        receive(d, false);
        setChat(c);
        setTypes(r.types);
      })
      .catch((e) => setLoadError(errorMessage(e)));
    return () => { alive = false; };
  }, [id, receive]);

  // poll while the background AI review runs
  const aiRunning = detail?.drawing.ai_status === 'running';
  useEffect(() => {
    if (!aiRunning) return;
    const t = setInterval(async () => {
      try {
        const d = await api.get(id);
        receive(d, false);
        if (d.drawing.ai_status === 'done') {
          const n = d.issues.filter((i) => i.source === 'ai' && i.status !== 'FIXED').length;
          toast(`AI review finished — ${n} additional finding${n === 1 ? '' : 's'}`, 'success');
        } else if (d.drawing.ai_status === 'error') toast(d.drawing.ai_error ?? 'AI review failed', 'error');
      } catch { /* keep polling */ }
    }, 2500);
    return () => clearInterval(t);
  }, [aiRunning, id, receive]);

  const run = useCallback(async (fn: () => Promise<Detail>, ok?: (d: Detail) => string | null) => {
    setBusy(true);
    try {
      const d = await fn();
      receive(d);
      const msg = ok?.(d);
      if (msg) toast(msg, 'success');
      return d;
    } catch (e) {
      toast(errorMessage(e), 'error');
      return null;
    } finally {
      setBusy(false);
    }
  }, [receive]);

  const edit = useCallback((ops: Op[], summary?: string) => run(() => api.edit(id, ops, summary)), [id, run]);

  const doc = detail?.document;
  const entities = useMemo(() => new Map((doc?.entities ?? []).map((e) => [e.id, e])), [doc]);
  const tagOf = (eid: string) => entities.get(eid)?.tag ?? eid;
  const active = useMemo(() => (detail?.issues ?? []).filter((i) => i.status === 'OPEN' || i.status === 'ACCEPTED'), [detail]);
  const numbered = useMemo(() => new Map(active.map((i, n) => [i.key, n + 1])), [active]);

  const focusObject = useCallback((oid: string) => {
    if (!doc) return;
    const e = doc.entities.find((x) => x.id === oid);
    const l = doc.lines.find((x) => x.id === oid);
    let box: BBox | null = null;
    if (e) {
      box = entityBox(doc, e);
      setSelection({ kind: 'entity', id: oid });
    } else if (l) {
      const xs = l.pts.map((p) => p[0]);
      const ys = l.pts.map((p) => p[1]);
      box = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
      setSelection({ kind: 'line', id: oid });
    }
    if (box) setFocus({ box: expand(box, 25), nonce: Date.now() });
  }, [doc]);

  const selectIssue = useCallback((key: string | null) => {
    setSelectedIssue(key);
    if (!key) return;
    setTab('issues');
    const iss = detail?.issues.find((i) => i.key === key);
    if (iss?.bbox) setFocus({ box: expand(iss.bbox, 30), nonce: Date.now() });
  }, [detail]);

  const head = detail?.drawing.head_rev ?? 1;
  const maxRev = detail?.drawing.max_rev ?? 1;
  const undo = useCallback(() => head > 1 && run(() => api.setHead(id, head - 1), () => `Undone — now at revision ${head - 1}`), [head, id, run]);
  const redo = useCallback(() => head < maxRev && run(() => api.setHead(id, head + 1), () => `Redone — revision ${head + 1}`), [head, maxRev, id, run]);

  const remove = useCallback((oid: string) => {
    setSelection(null);
    edit([{ op: 'delete', id: oid }], `Deleted ${tagOf(oid)}`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [edit, entities]);

  const rotate = useCallback((oid: string) => {
    const e = entities.get(oid);
    if (e) edit([{ op: 'rotate', id: oid, angle: (e.rot + 90) % 360 }], `Rotated ${tagOf(oid)}`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [edit, entities]);

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      const t = ev.target as HTMLElement;
      if (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT') return;
      const mod = ev.metaKey || ev.ctrlKey;
      if (mod && ev.key.toLowerCase() === 'z') {
        ev.preventDefault();
        if (ev.shiftKey) redo(); else undo();
      } else if (mod && ev.key.toLowerCase() === 'y') {
        ev.preventDefault();
        redo();
      } else if (ev.key === 'Escape') {
        setMode({ kind: 'select' });
        setSelection(null);
        setSelectedIssue(null);
      } else if ((ev.key === 'Delete' || ev.key === 'Backspace') && selection && !busy) {
        ev.preventDefault();
        remove(selection.id);
      } else if (ev.key.toLowerCase() === 'r' && !mod && selection?.kind === 'entity' && !busy) {
        rotate(selection.id);
      } else if (ev.key.toLowerCase() === 'f' && !mod && doc) {
        setFocus({ box: doc.bounds, nonce: Date.now() });
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [undo, redo, selection, busy, remove, rotate, doc]);

  const send = async (message: string) => {
    setChatBusy(true);
    setChat((c) => [...c, { id: -Date.now(), role: 'user', content: message, actions: [], rev_no: null, engine: '', created_at: new Date().toISOString() }]);
    try {
      const d = await api.send(id, message);
      receive(d);
    } catch (e) {
      toast(errorMessage(e), 'error');
      api.chat(id).then(setChat).catch(() => undefined);
    } finally {
      setChatBusy(false);
    }
  };

  const startAiReview = async () => {
    try {
      await api.aiReview(id);
      receive(await api.get(id), false);
      toast('AI review started — findings will appear in the register', 'info');
    } catch (e) {
      toast(errorMessage(e), 'error');
    }
  };

  if (loadError) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-4 bg-[#0b0f17] text-slate-300">
        <TriangleAlert className="h-10 w-10 text-rose-400" />
        <p>{loadError}</p>
        <button onClick={onBack} className="rounded-lg bg-slate-800 px-4 py-2 text-sm hover:bg-slate-700">Back to inspections</button>
      </div>
    );
  }
  if (!detail || !doc) {
    return (
      <div className="flex h-screen items-center justify-center bg-[#0b0f17] text-slate-400">
        <Loader2 className="mr-3 h-6 w-6 animate-spin text-blue-400" /> Loading drawing…
      </div>
    );
  }

  const { drawing, ai } = detail;
  const stats = drawing.stats;
  const outstanding = stats.open + stats.accepted;
  const grouped = types.reduce<Record<string, ComponentType[]>>((acc, t) => {
    (acc[t.category] ??= []).push(t);
    return acc;
  }, {});

  return (
    <div className="flex h-screen flex-col bg-[#0b0f17] text-slate-200">
      {/* toolbar */}
      <header className="z-30 flex h-14 shrink-0 items-center gap-2 border-b border-slate-800 bg-slate-950/80 px-3 whitespace-nowrap backdrop-blur lg:gap-3">
        <button onClick={onBack} title="All inspections" className="rounded-lg p-2 text-slate-400 hover:bg-slate-800 hover:text-white"><ArrowLeft className="h-5 w-5" /></button>
        <div className="flex min-w-0 items-center gap-2.5">
          <FileText className="h-4 w-4 shrink-0 text-blue-400" />
          <span className="truncate text-sm font-semibold text-white" title={drawing.filename}>{drawing.filename}</span>
          <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] font-bold uppercase text-slate-400">{drawing.format}</span>
        </div>

        <Menu align="left" button={(open) => (
          <button className={`flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium ring-1 transition ${open ? 'bg-slate-800 ring-slate-600' : 'ring-slate-800 hover:bg-slate-900'}`}>
            <History className="h-3.5 w-3.5 text-slate-400" /> Rev {head}<span className="text-slate-500">/{maxRev}</span> <ChevronDown className="h-3 w-3 text-slate-500" />
          </button>
        )}>
          {(close) => (
            <div className="max-h-96 w-80 overflow-y-auto py-1">
              <div className="px-3 py-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500">Revision history</div>
              {[...detail.revisions].reverse().map((r) => {
                const a = AUTHOR_ICON[r.author] ?? AUTHOR_ICON.user;
                return (
                  <MenuItem key={r.rev_no} onClick={() => { close(); if (r.rev_no !== head) run(() => api.setHead(id, r.rev_no)); }}
                    icon={<a.icon className={`h-4 w-4 ${a.cls}`} />}
                    label={<span className={r.rev_no === head ? 'font-semibold text-white' : ''}>Rev {r.rev_no} · {a.label}{r.rev_no === head ? ' (current)' : ''}</span>}
                    hint={<><span className="line-clamp-2">{r.summary}</span><span className="text-slate-600">{timeAgo(r.created_at)}</span></>} />
                );
              })}
            </div>
          )}
        </Menu>

        <div className="flex shrink-0 items-center rounded-lg ring-1 ring-slate-800">
          <button onClick={undo} disabled={head <= 1 || busy} title="Undo (⌘Z)" className="rounded-l-lg p-2 text-slate-300 hover:bg-slate-800 disabled:opacity-30"><Undo2 className="h-4 w-4" /></button>
          <button onClick={redo} disabled={head >= maxRev || busy} title="Redo (⇧⌘Z)" className="rounded-r-lg border-l border-slate-800 p-2 text-slate-300 hover:bg-slate-800 disabled:opacity-30"><Redo2 className="h-4 w-4" /></button>
        </div>

        <Menu align="left" button={() => (
          <button disabled={busy} title="Add symbol" className="flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-slate-200 ring-1 ring-slate-800 hover:bg-slate-900">
            <Plus className="h-3.5 w-3.5" /> <span className="hidden lg:inline">Add symbol</span>
          </button>
        )}>
          {(close) => (
            <div className="max-h-[28rem] w-64 overflow-y-auto py-1">
              {Object.entries(grouped).map(([cat, ts]) => (
                <div key={cat}>
                  <div className="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">{cat}</div>
                  {ts.map((t) => (
                    <MenuItem key={t.type} label={t.name} hint={t.prefixes.length ? `Tag ${t.prefixes.join(' / ')}-xxx` : undefined}
                      onClick={() => { close(); setSelection(null); setMode({ kind: 'place', type: t.type }); }} />
                  ))}
                </div>
              ))}
            </div>
          )}
        </Menu>

        <div className="flex-1" />

        {outstanding === 0 ? (
          <span className="flex shrink-0 items-center gap-1.5 rounded-full bg-emerald-500/15 px-3 py-1 text-xs font-semibold text-emerald-300 ring-1 ring-emerald-500/30">
            <CircleCheck className="h-3.5 w-3.5" /> <span className="hidden lg:inline">All findings closed</span>
          </span>
        ) : (
          <span className="flex shrink-0 items-center gap-1.5 rounded-full bg-amber-500/10 px-3 py-1 text-xs font-semibold text-amber-200 ring-1 ring-amber-500/30">
            <TriangleAlert className="h-3.5 w-3.5" /> {outstanding}<span className="hidden lg:inline"> outstanding</span>
          </span>
        )}

        <button onClick={startAiReview} disabled={!ai.enabled || aiRunning}
          title={!ai.enabled ? 'Add GROQ_API_KEY to backend/.env to enable the AI review' : drawing.ai_status === 'error' ? `Last run failed: ${drawing.ai_error}` : 'Ask the AI for findings the rules cannot catch'}
          className="flex shrink-0 items-center gap-1.5 rounded-lg bg-violet-600/90 px-3 py-1.5 text-xs font-semibold text-white shadow-lg shadow-violet-950/40 transition hover:bg-violet-500 disabled:cursor-not-allowed disabled:bg-slate-800 disabled:text-slate-500 disabled:shadow-none">
          {aiRunning ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : drawing.ai_status === 'error' ? <TriangleAlert className="h-3.5 w-3.5 text-rose-300" /> : <Sparkles className="h-3.5 w-3.5" />}
          <span className="hidden lg:inline">{aiRunning ? 'AI reviewing…' : drawing.ai_status === 'done' ? 'Re-run AI review' : 'AI review'}</span>
        </button>

        <Menu button={() => (
          <button className="flex shrink-0 items-center gap-1.5 rounded-lg bg-slate-800 px-3 py-1.5 text-xs font-semibold text-white ring-1 ring-slate-700 hover:bg-slate-700">
            <Download className="h-3.5 w-3.5" /> Export <ChevronDown className="h-3 w-3" />
          </button>
        )}>
          {(close) => (
            <div className="w-72 py-1">
              {([
                ['report-pdf', FileText, 'Check report (PDF)', 'Drawing with clouds + issue register'],
                ['markup-dxf', Workflow, 'Marked-up DXF', 'Revision clouds on a CHECKER layer'],
                ['dxf', FileCode2, 'Corrected DXF', `Current revision (rev ${head})`],
                ['original', FileDown, 'Original upload', drawing.filename],
              ] as const).map(([kind, Icon, label, hint]) => (
                <a key={kind} href={api.exportUrl(id, kind)} onClick={close}
                  className="flex items-start gap-3 px-3 py-2.5 text-sm text-slate-200 hover:bg-slate-800">
                  <Icon className="mt-0.5 h-4 w-4 text-slate-400" />
                  <span><span className="block">{label}</span><span className="block truncate text-xs text-slate-500">{hint}</span></span>
                </a>
              ))}
            </div>
          )}
        </Menu>
      </header>

      <div className="flex min-h-0 flex-1">
        {/* canvas */}
        <main className="relative min-w-0 flex-1 overflow-hidden bg-[#0c1220]">
          <DrawingCanvas
            doc={doc}
            attachments={detail.topology.attachments}
            issues={active}
            selectedIssue={selectedIssue}
            selection={selection}
            changed={flash}
            mode={mode}
            focus={focus}
            onSelect={(s) => { setSelection(s); if (s) setSelectedIssue(null); }}
            onSelectIssue={selectIssue}
            onMove={(eid, x, y) => edit([{ op: 'move', id: eid, x, y }], `Moved ${tagOf(eid)}`)}
            onPlace={(p: Pt) => {
              const type = mode.kind === 'place' ? mode.type : null;
              setMode({ kind: 'select' });
              if (type) edit([{ op: 'add_entity', type, x: +p[0].toFixed(2), y: +p[1].toFixed(2) }], `Added ${typeName(type)}`);
            }}
            onConnect={(target) => {
              if (mode.kind !== 'connect' || target === mode.from) return;
              const kind = mode.line ?? 'process';
              setMode({ kind: 'select' });
              edit([{ op: 'connect', from: mode.from, to: target, kind }], `Connected ${tagOf(mode.from)} → ${tagOf(target)}`);
            }}
          />

          {selection && mode.kind === 'select' && (
            <Inspector doc={doc} selection={selection} issues={detail.issues} busy={busy}
              onClose={() => setSelection(null)}
              onRetag={(oid, tag) => edit([{ op: 'set_tag', id: oid, tag }], `Retagged ${tagOf(oid)} → ${tag}`)}
              onRotate={rotate}
              onDelete={remove}
              onConnect={(oid, kind) => setMode({ kind: 'connect', from: oid, line: kind })}
              onSelectIssue={selectIssue} />
          )}

          {mode.kind !== 'select' && (
            <div className="absolute top-3 left-1/2 z-20 flex -translate-x-1/2 items-center gap-3 rounded-full border border-blue-500/40 bg-slate-900/95 px-4 py-2 text-sm text-slate-200 shadow-xl">
              {mode.kind === 'place'
                ? <>Click on the drawing to place a <b className="text-white">{typeName(mode.type)}</b></>
                : <>Click the component to {mode.line === 'signal' ? 'signal' : 'pipe'} <b className="text-white">{tagOf(mode.from)}</b> to</>}
              <span className="text-xs text-slate-500"><Kbd>Esc</Kbd> cancel</span>
            </div>
          )}

          {doc.source.format === 'pdf' && (
            <div className="absolute top-3 right-3 z-10 max-w-xs rounded-lg border border-amber-500/30 bg-amber-950/80 px-3 py-2 text-xs text-amber-100">
              PDF input: tags and text are checked, but pipe connectivity is not available. Upload the DXF for the full rule set.
            </div>
          )}
          {busy && <div className="absolute top-0 right-0 left-0 h-0.5 animate-pulse bg-blue-500" />}
        </main>

        {/* side panel */}
        <aside className="flex w-[340px] shrink-0 flex-col border-l border-slate-800 bg-[#0e1422] xl:w-[400px]">
          <div className="flex border-b border-slate-800">
            {([
              ['issues', ListChecks, 'Issue register', outstanding],
              ['chat', MessageSquareText, 'Assistant', null],
            ] as const).map(([key, Icon, label, count]) => (
              <button key={key} onClick={() => setTab(key)}
                className={`flex flex-1 items-center justify-center gap-2 border-b-2 py-3 text-sm font-medium transition ${tab === key ? 'border-blue-500 text-white' : 'border-transparent text-slate-400 hover:text-slate-200'}`}>
                <Icon className="h-4 w-4" /> {label}
                {count !== null && count > 0 && <span className="rounded-full bg-slate-800 px-1.5 text-[10px] tabular-nums text-slate-300">{count}</span>}
              </button>
            ))}
          </div>
          <div className="min-h-0 flex-1">
            {tab === 'issues' ? (
              <IssuePanel
                issues={detail.issues}
                numbered={numbered}
                stats={stats}
                entities={entities}
                selected={selectedIssue}
                busy={busy}
                onSelect={selectIssue}
                onFix={(key) => run(() => api.fix(id, key), (d) => d.messages?.join('\n') ?? 'Fix applied')}
                onReview={(key, status, comment) => run(() => api.review(id, key, status, comment))}
                onAutofix={() => run(() => api.autofix(id), (d) => `Auto-fix applied ${d.messages?.length ?? 0} change(s) as revision ${d.drawing.head_rev}`)}
                onFocusObject={focusObject}
              />
            ) : (
              <ChatPanel messages={chat} ai={ai} issues={detail.issues} entities={entities} busy={chatBusy}
                onSend={send} onJumpToRevision={(rev) => rev !== head && run(() => api.setHead(id, rev))} />
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
