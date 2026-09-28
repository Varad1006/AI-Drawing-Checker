import { useEffect, useMemo, useState } from 'react';
import { Ban, Check, CircleCheck, Loader2, RotateCcw, Sparkles, Wand2, Wrench } from 'lucide-react';
import type { Entity, Issue, Severity, Stats } from '../types';
import { SEVERITY_COLOR } from '../lib/draw';
import { SeverityBadge, StatusText } from './ui';

interface Props {
  issues: Issue[];
  numbered: Map<string, number>;
  stats: Stats;
  entities: Map<string, Entity>;
  selected: string | null;
  busy: boolean;
  onSelect: (key: string | null) => void;
  onFix: (key: string) => void;
  onReview: (key: string, status: 'OPEN' | 'ACCEPTED' | 'REJECTED', comment: string) => void;
  onAutofix: () => void;
  onFocusObject: (id: string) => void;
}

const SEVERITIES: Severity[] = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];

export default function IssuePanel(p: Props) {
  const [sev, setSev] = useState<Set<Severity>>(new Set());
  const [source, setSource] = useState<'all' | 'rule' | 'ai'>('all');
  const [showClosed, setShowClosed] = useState(true);

  const visible = useMemo(
    () => p.issues.filter((i) =>
      (sev.size === 0 || sev.has(i.severity)) &&
      (source === 'all' || i.source === source) &&
      (showClosed || (i.status !== 'FIXED' && i.status !== 'REJECTED'))),
    [p.issues, sev, source, showClosed],
  );

  useEffect(() => {
    if (p.selected) document.getElementById(`issue-${p.selected}`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [p.selected]);

  const total = p.stats.open + p.stats.accepted + p.stats.rejected + p.stats.fixed;
  const progress = total ? ((p.stats.fixed + p.stats.rejected + p.stats.accepted) / total) * 100 : 100;

  return (
    <div className="flex h-full flex-col">
      <div className="space-y-3 border-b border-slate-800 p-4">
        <div className="grid grid-cols-4 gap-2 text-center">
          {[
            ['Open', p.stats.open, 'text-white'],
            ['Accepted', p.stats.accepted, 'text-amber-300'],
            ['Rejected', p.stats.rejected, 'text-slate-400'],
            ['Fixed', p.stats.fixed, 'text-emerald-400'],
          ].map(([label, n, cls]) => (
            <div key={label as string} className="rounded-lg bg-slate-900 py-2 ring-1 ring-slate-800">
              <div className={`text-lg font-bold tabular-nums ${cls}`}>{n}</div>
              <div className="text-[10px] font-medium uppercase tracking-wider text-slate-500">{label}</div>
            </div>
          ))}
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-slate-800" title="Findings resolved or dispositioned">
          <div className="h-full rounded-full bg-gradient-to-r from-emerald-500 to-teal-400 transition-all duration-500" style={{ width: `${progress}%` }} />
        </div>
        <button
          onClick={p.onAutofix}
          disabled={p.busy || p.stats.fixable === 0}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-emerald-600 px-3 py-2 text-sm font-semibold text-white shadow-lg shadow-emerald-900/30 transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-slate-800 disabled:text-slate-500 disabled:shadow-none"
        >
          {p.busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
          {p.stats.fixable ? `Auto-fix ${p.stats.fixable} mechanical issue${p.stats.fixable > 1 ? 's' : ''}` : 'Nothing left to auto-fix'}
        </button>
        <div className="flex flex-wrap items-center gap-1.5">
          {SEVERITIES.map((s) => {
            const on = sev.has(s);
            return (
              <button key={s} onClick={() => setSev((cur) => { const n = new Set(cur); if (on) n.delete(s); else n.add(s); return n; })}
                className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 transition ${on ? 'bg-slate-700 text-white ring-slate-500' : 'text-slate-400 ring-slate-700 hover:text-slate-200'}`}>
                <span className="h-2 w-2 rounded-full" style={{ background: SEVERITY_COLOR[s] }} />
                {s[0] + s.slice(1).toLowerCase()} <span className="tabular-nums text-slate-500">{p.stats.by_severity[s]}</span>
              </button>
            );
          })}
          <select value={source} onChange={(e) => setSource(e.target.value as typeof source)}
            className="ml-auto rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-[11px] text-slate-300">
            <option value="all">All sources</option>
            <option value="rule">Rule engine</option>
            <option value="ai">AI review</option>
          </select>
        </div>
        <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-400">
          <input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} className="accent-blue-500" />
          Show fixed &amp; rejected findings
        </label>
      </div>

      <div className="flex-1 space-y-2 overflow-y-auto p-3">
        {visible.length === 0 && (
          <div className="flex flex-col items-center gap-2 py-12 text-center text-sm text-slate-500">
            <CircleCheck className="h-8 w-8 text-emerald-500" />
            {p.issues.length ? 'No findings match the filters.' : 'The drawing passed every check.'}
          </div>
        )}
        {visible.map((iss) => (
          <IssueCard key={iss.key} issue={iss} n={p.numbered.get(iss.key)} isSelected={p.selected === iss.key} {...p} />
        ))}
      </div>
    </div>
  );
}

function IssueCard({ issue, n, isSelected: selected, entities, busy, onSelect, onFix, onReview, onFocusObject }: Props & { issue: Issue; n?: number; isSelected: boolean }) {
  const [comment, setComment] = useState(issue.comment);
  const [synced, setSynced] = useState(issue.comment);
  if (synced !== issue.comment) {
    setSynced(issue.comment);
    setComment(issue.comment);
  }
  const closed = issue.status === 'FIXED' || issue.status === 'REJECTED';
  const color = SEVERITY_COLOR[issue.severity];

  return (
    <div id={`issue-${issue.key}`}
      className={`overflow-hidden rounded-xl border transition ${selected ? 'border-blue-500/70 bg-slate-900 ring-1 ring-blue-500/30' : 'border-slate-800 bg-slate-900/60 hover:border-slate-700'} ${closed ? 'opacity-60' : ''}`}>
      <button className="flex w-full gap-3 p-3 text-left" onClick={() => onSelect(selected ? null : issue.key)}>
        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-slate-950"
          style={{ background: issue.status === 'FIXED' ? '#10b981' : closed ? '#475569' : color }}>
          {issue.status === 'FIXED' ? <Check className="h-3.5 w-3.5" /> : issue.status === 'REJECTED' ? <Ban className="h-3 w-3" /> : n}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-1.5">
            <SeverityBadge severity={issue.severity} />
            <span className="font-mono text-[10px] text-slate-500">{issue.rule_id}</span>
            <span className="text-[10px] text-slate-500">· {issue.category}</span>
            {issue.source === 'ai' && (
              <span className="flex items-center gap-1 rounded bg-violet-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-violet-300 ring-1 ring-violet-500/30">
                <Sparkles className="h-3 w-3" /> AI {Math.round(issue.confidence * 100)}%
              </span>
            )}
            <span className="ml-auto"><StatusText status={issue.status} /></span>
          </span>
          <span className={`mt-1.5 block text-sm font-semibold leading-snug ${closed ? 'text-slate-400' : 'text-slate-100'}`}>{issue.title}</span>
        </span>
      </button>

      {selected && (
        <div className="space-y-3 border-t border-slate-800 px-3 pt-3 pb-3 text-sm">
          <p className="leading-relaxed text-slate-300">{issue.description}</p>
          {issue.recommendation && (
            <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-2.5">
              <div className="mb-1 text-[10px] font-bold uppercase tracking-wider text-amber-300/90">Recommendation</div>
              <p className="text-slate-200">{issue.recommendation}</p>
            </div>
          )}
          {(issue.entities.length > 0 || issue.lines.length > 0) && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Objects</span>
              {[...issue.entities, ...issue.lines].map((id) => (
                <button key={id} onClick={() => onFocusObject(id)}
                  className="rounded-md bg-slate-800 px-2 py-0.5 font-mono text-[11px] text-slate-200 ring-1 ring-slate-700 hover:bg-slate-700">
                  {entities.get(id)?.tag ?? id}
                </button>
              ))}
            </div>
          )}
          {issue.status !== 'FIXED' && (
            <>
              {issue.fix && issue.status !== 'REJECTED' && (
                <button disabled={busy} onClick={() => onFix(issue.key)}
                  className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white transition hover:bg-blue-500 disabled:opacity-50">
                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wrench className="h-4 w-4" />} Apply fix: {issue.fix.label}
                </button>
              )}
              <textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={2}
                placeholder="Checker comment (optional) — e.g. why it is waived"
                className="w-full resize-none rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-2 text-sm text-slate-200 placeholder-slate-600 outline-none focus:border-blue-500" />
              <div className="grid grid-cols-2 gap-2">
                {issue.status === 'OPEN' ? (
                  <>
                    <button disabled={busy} onClick={() => onReview(issue.key, 'ACCEPTED', comment)}
                      className="flex items-center justify-center gap-1.5 rounded-lg border border-amber-500/40 px-3 py-1.5 text-xs font-semibold text-amber-200 hover:bg-amber-500/10">
                      <Check className="h-3.5 w-3.5" /> Accept (to fix)
                    </button>
                    <button disabled={busy} onClick={() => onReview(issue.key, 'REJECTED', comment)}
                      className="flex items-center justify-center gap-1.5 rounded-lg border border-slate-600 px-3 py-1.5 text-xs font-semibold text-slate-300 hover:bg-slate-800">
                      <Ban className="h-3.5 w-3.5" /> Reject / waive
                    </button>
                  </>
                ) : (
                  <button disabled={busy} onClick={() => onReview(issue.key, 'OPEN', comment)}
                    className="col-span-2 flex items-center justify-center gap-1.5 rounded-lg border border-slate-600 px-3 py-1.5 text-xs font-semibold text-slate-300 hover:bg-slate-800">
                    <RotateCcw className="h-3.5 w-3.5" /> Reopen
                  </button>
                )}
              </div>
            </>
          )}
          {issue.status === 'FIXED' && (
            <p className="flex items-center gap-2 text-xs text-emerald-400"><CircleCheck className="h-4 w-4" /> Resolved by an edit in this check — no longer present on the current revision.</p>
          )}
        </div>
      )}
    </div>
  );
}
