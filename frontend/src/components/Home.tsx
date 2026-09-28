import { useEffect, useRef, useState } from 'react';
import {
  BookOpen, ChevronRight, CircleCheck, Cpu, FileText, FileUp, HardHat, Loader2, MessageSquareText, PlayCircle,
  ShieldCheck, Sparkles, Terminal, Trash2, Wand2, X,
} from 'lucide-react';
import { api, errorMessage } from '../api';
import type { AIInfo, DrawingSummary, RuleInfo, Severity } from '../types';
import { SEVERITY_COLOR } from '../lib/draw';
import { toast } from '../lib/toast';
import { SeverityBadge } from './ui';

const SEVERITIES: Severity[] = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];

export default function Home({ onOpen }: { onOpen: (id: number) => void }) {
  const [drawings, setDrawings] = useState<DrawingSummary[] | null>(null);
  const [ai, setAi] = useState<AIInfo | null>(null);
  const [backendDown, setBackendDown] = useState(false);
  const [busy, setBusy] = useState<'upload' | 'demo' | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [rules, setRules] = useState<RuleInfo[] | null>(null);
  const [showRules, setShowRules] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = () =>
    api.list().then((d) => { setDrawings(d); setBackendDown(false); }).catch(() => { setBackendDown(true); setDrawings([]); });

  useEffect(() => {
    refresh();
    api.health().then((h) => setAi(h.ai)).catch(() => setBackendDown(true));
    api.rules().then((r) => setRules(r.rules)).catch(() => undefined);
  }, []);

  const upload = async (file: File) => {
    if (!/\.(dxf|pdf)$/i.test(file.name)) {
      toast('Please choose a .dxf or .pdf drawing', 'error');
      return;
    }
    setBusy('upload');
    try {
      const d = await api.upload(file);
      toast(`${file.name}: ${d.stats.open} finding${d.stats.open === 1 ? '' : 's'}`, d.stats.open ? 'info' : 'success');
      onOpen(d.id);
    } catch (e) {
      toast(errorMessage(e), 'error');
    } finally {
      setBusy(null);
    }
  };

  const demo = async () => {
    setBusy('demo');
    try {
      onOpen((await api.demo()).id);
    } catch (e) {
      toast(errorMessage(e), 'error');
      setBusy(null);
    }
  };

  const remove = async (d: DrawingSummary) => {
    if (!confirm(`Delete "${d.filename}" and its revision history?`)) return;
    try {
      await api.remove(d.id);
      refresh();
    } catch (e) {
      toast(errorMessage(e), 'error');
    }
  };

  return (
    <div className="relative min-h-screen overflow-x-clip bg-[#0b0f17] text-slate-300">
      <div className="pointer-events-none absolute -top-40 -left-40 h-[36rem] w-[36rem] rounded-full bg-blue-700/10 blur-[140px]" />
      <div className="pointer-events-none absolute top-60 -right-40 h-[30rem] w-[30rem] rounded-full bg-violet-700/10 blur-[140px]" />

      <header className="sticky top-0 z-20 border-b border-slate-800/80 bg-[#0b0f17]/80 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-600 shadow-[0_0_18px_rgba(37,99,235,0.45)]">
              <HardHat className="h-5 w-5 text-white" />
            </div>
            <span className="text-lg font-bold tracking-wide text-white">LEAD CHECKER</span>
          </div>
          <div className="flex items-center gap-2 text-sm">
            {ai && (ai.enabled ? (
              <span className="hidden items-center gap-1.5 rounded-full bg-violet-500/10 px-3 py-1 text-xs font-medium text-violet-300 ring-1 ring-violet-500/30 sm:flex">
                <Sparkles className="h-3.5 w-3.5" /> Groq AI · {ai.model}
              </span>
            ) : (
              <span className="hidden items-center gap-1.5 rounded-full bg-slate-800/80 px-3 py-1 text-xs font-medium text-slate-400 ring-1 ring-slate-700 sm:flex"
                title="Set GROQ_API_KEY in backend/.env to enable the AI review and natural-language editing">
                <Terminal className="h-3.5 w-3.5" /> AI offline — rules + command assistant
              </span>
            ))}
            <button onClick={() => setShowRules(true)} className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-slate-300 hover:bg-slate-800 hover:text-white">
              <BookOpen className="h-4 w-4" /> Rules
            </button>
          </div>
        </div>
      </header>

      <main className="relative mx-auto max-w-6xl px-6 pt-14 pb-20">
        {backendDown && (
          <div className="mb-8 rounded-xl border border-rose-500/40 bg-rose-950/40 px-4 py-3 text-sm text-rose-200">
            Cannot reach the API on port 8000. Start it with <code className="rounded bg-black/30 px-1.5">cd backend && ./venv/bin/uvicorn app.main:app --reload</code>
          </div>
        )}

        <section className="grid items-center gap-12 lg:grid-cols-[1.1fr_1fr]">
          <div className="space-y-6">
            <span className="inline-flex items-center gap-2 rounded-full bg-blue-500/10 px-3 py-1 text-xs font-semibold text-blue-300 ring-1 ring-blue-500/30">
              <ShieldCheck className="h-3.5 w-3.5" /> Automated lead-checker QA for P&amp;IDs
            </span>
            <h1 className="text-4xl leading-tight font-extrabold text-white md:text-5xl">
              Check drawings like a <span className="bg-gradient-to-r from-blue-400 to-cyan-300 bg-clip-text text-transparent">lead engineer</span>, fix them by conversation.
            </h1>
            <p className="max-w-xl text-lg leading-relaxed text-slate-400">
              Upload a DXF or PDF. The CAD topology is extracted, 15 deterministic engineering rules run instantly,
              Groq AI adds a second opinion — then fix issues with one click or by asking the assistant to edit the drawing.
            </p>
            <div className="grid max-w-xl grid-cols-2 gap-3 text-sm">
              {[
                [Cpu, 'Rule engine', 'Tags, connectivity, safety, instruments'],
                [Sparkles, 'AI review', 'Findings the rules cannot catch'],
                [MessageSquareText, 'Chat editing', 'The assistant edits the CAD model'],
                [Wand2, 'Auto-fix & export', 'Corrected DXF, mark-up, PDF report'],
              ].map(([Icon, title, sub]) => {
                const I = Icon as typeof Cpu;
                return (
                  <div key={title as string} className="flex gap-3 rounded-xl border border-slate-800 bg-slate-900/50 p-3">
                    <I className="mt-0.5 h-5 w-5 shrink-0 text-blue-400" />
                    <div><div className="font-semibold text-slate-200">{title as string}</div><div className="text-xs text-slate-500">{sub as string}</div></div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="relative overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/80 p-7 shadow-2xl shadow-black/40">
            <div className="absolute top-0 left-0 h-1 w-full bg-gradient-to-r from-blue-500 via-cyan-400 to-violet-500" />
            <h2 className="text-xl font-bold text-white">New inspection</h2>
            <p className="mt-1 mb-5 text-sm text-slate-400">AutoCAD DXF gives the full rule set; vector PDFs get tag and text checks.</p>
            <div
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer.files[0]; if (f) upload(f); }}
              onClick={() => !busy && fileInput.current?.click()}
              className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-12 text-center transition ${dragOver ? 'border-blue-400 bg-blue-500/10' : 'border-slate-700 bg-slate-950/50 hover:border-blue-500/50 hover:bg-slate-900'}`}
            >
              {busy === 'upload' ? <Loader2 className="mb-3 h-10 w-10 animate-spin text-blue-400" /> : <FileUp className="mb-3 h-10 w-10 text-slate-500" />}
              <span className="font-medium text-slate-200">{busy === 'upload' ? 'Parsing and checking…' : 'Drop a .dxf or .pdf here'}</span>
              <span className="mt-1 text-xs text-slate-500">or click to browse · max 25 MB</span>
              <input ref={fileInput} type="file" accept=".dxf,.pdf" className="hidden"
                onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ''; }} />
            </div>
            <button onClick={demo} disabled={!!busy}
              className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 py-3 text-sm font-bold text-white shadow-[0_0_18px_rgba(37,99,235,0.3)] transition hover:bg-blue-500 disabled:opacity-50">
              {busy === 'demo' ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlayCircle className="h-4 w-4" />}
              Open live demo — water treatment P&amp;ID with 9 seeded errors
            </button>
          </div>
        </section>

        <section className="mt-16">
          <h3 className="mb-4 text-xs font-bold tracking-widest text-slate-500 uppercase">Recent inspections</h3>
          {drawings === null ? (
            <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</div>
          ) : drawings.length === 0 ? (
            <p className="rounded-xl border border-dashed border-slate-800 px-4 py-8 text-center text-sm text-slate-500">No inspections yet — upload a drawing or open the demo.</p>
          ) : (
            <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
              {drawings.map((d) => {
                const outstanding = d.stats.open + d.stats.accepted;
                return (
                  <div key={d.id} onClick={() => onOpen(d.id)}
                    className="group flex cursor-pointer flex-col gap-3 rounded-xl border border-slate-800 bg-slate-900/70 p-4 transition hover:border-slate-600 hover:bg-slate-900">
                    <div className="flex items-start gap-3">
                      <FileText className="mt-0.5 h-8 w-8 shrink-0 text-slate-600 transition group-hover:text-blue-400" />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-semibold text-slate-100" title={d.filename}>{d.filename}</div>
                        <div className="mt-0.5 text-[11px] text-slate-500 uppercase">{d.format} · rev {d.head_rev} · {new Date(d.created_at).toLocaleString()}</div>
                      </div>
                      <button onClick={(e) => { e.stopPropagation(); remove(d); }} title="Delete"
                        className="rounded p-1 text-slate-600 opacity-0 transition group-hover:opacity-100 hover:bg-slate-800 hover:text-rose-300">
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                    <div className="flex items-center gap-3 text-xs">
                      {outstanding === 0 ? (
                        <span className="flex items-center gap-1 font-semibold text-emerald-400"><CircleCheck className="h-3.5 w-3.5" /> Clean</span>
                      ) : (
                        <span className="font-semibold text-slate-200">{outstanding} outstanding</span>
                      )}
                      <div className="flex items-center gap-1.5">
                        {SEVERITIES.filter((s) => d.stats.by_severity[s]).map((s) => (
                          <span key={s} className="flex items-center gap-1 text-slate-400">
                            <span className="h-2 w-2 rounded-full" style={{ background: SEVERITY_COLOR[s] }} />{d.stats.by_severity[s]}
                          </span>
                        ))}
                      </div>
                      {d.stats.fixed > 0 && <span className="text-emerald-400/80">{d.stats.fixed} fixed</span>}
                      <ChevronRight className="ml-auto h-4 w-4 text-slate-600 group-hover:text-slate-300" />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </main>

      {showRules && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onClick={() => setShowRules(false)}>
          <div className="flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-slate-800 px-5 py-4">
              <div>
                <h2 className="text-lg font-bold text-white">Rule catalogue</h2>
                <p className="text-xs text-slate-500">Deterministic checks run on every revision. Rules marked “DXF” need pipe connectivity.</p>
              </div>
              <button onClick={() => setShowRules(false)} className="rounded p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white"><X className="h-5 w-5" /></button>
            </div>
            <div className="divide-y divide-slate-800 overflow-y-auto">
              {(rules ?? []).map((r) => (
                <div key={r.id} className="flex gap-4 px-5 py-3">
                  <span className="w-12 shrink-0 font-mono text-xs text-slate-500">{r.id}</span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold text-slate-100">{r.title}</span>
                      <SeverityBadge severity={r.severity} />
                      <span className="text-[11px] text-slate-500">{r.category}</span>
                      {r.needs_topology && <span className="rounded bg-slate-800 px-1.5 text-[10px] font-semibold text-slate-400">DXF</span>}
                    </div>
                    <p className="mt-1 text-sm text-slate-400">{r.description}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
