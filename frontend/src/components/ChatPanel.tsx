import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Bot, CornerDownLeft, History, Loader2, Sparkles, Terminal, Wrench } from 'lucide-react';
import type { AIInfo, ChatMessage, Entity, Issue } from '../types';

interface Props {
  messages: ChatMessage[];
  ai: AIInfo;
  issues: Issue[];
  entities: Map<string, Entity>;
  busy: boolean;
  onSend: (text: string) => void;
  onJumpToRevision: (rev: number) => void;
}

function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) =>
    part.startsWith('**') ? <strong key={i} className="font-semibold text-white">{part.slice(2, -2)}</strong>
      : part.startsWith('`') ? <code key={i} className="rounded bg-slate-800 px-1 font-mono text-[12px] text-sky-200">{part.slice(1, -1)}</code>
      : part,
  );
}

function RichText({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let bullets: string[] = [];
  const flush = () => {
    if (bullets.length) {
      blocks.push(<ul key={blocks.length} className="ml-4 list-disc space-y-0.5">{bullets.map((b, i) => <li key={i}>{inline(b)}</li>)}</ul>);
      bullets = [];
    }
  };
  for (const raw of text.split('\n')) {
    const line = raw.trimEnd();
    const m = line.match(/^\s*(?:[-*•]|\d+\.)\s+(.*)$/);
    if (m) bullets.push(m[1]);
    else {
      flush();
      if (line.trim()) blocks.push(<p key={blocks.length}>{inline(line)}</p>);
    }
  }
  flush();
  return <div className="space-y-1.5">{blocks}</div>;
}

export default function ChatPanel({ messages, ai, issues, entities, busy, onSend, onJumpToRevision }: Props) {
  const [text, setText] = useState('');
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, busy]);

  const suggestions = useMemo(() => {
    const open = issues.filter((i) => i.status === 'OPEN');
    const tagOf = (i: Issue) => entities.get(i.entities[0])?.tag ?? i.entities[0];
    const out: string[] = [];
    if (ai.enabled) {
      if (open.some((i) => i.fix)) out.push('Fix everything that can be fixed automatically');
      const loop = open.find((i) => i.rule_id === 'R011');
      if (loop) out.push(`Add the missing transmitter and controller for ${tagOf(loop)} and wire the loop`);
      const crit = open.find((i) => i.severity === 'CRITICAL');
      if (crit) out.push(`Why is "${crit.title}" critical?`);
      if (open.some((i) => i.rule_id === 'R014')) out.push('Sign the title block as checked by LEAD CHECKER');
      out.push('Add a pressure gauge on the discharge of each pump');
    } else {
      if (open.some((i) => i.fix)) out.push('fix all');
      const lvl = open.find((i) => i.rule_id === 'R009');
      if (lvl) out.push(`add a level transmitter near ${tagOf(lvl)} right`);
      if (open.some((i) => i.rule_id === 'R014')) out.push('set checked by to LEAD CHECKER');
      out.push('help');
    }
    return out.slice(0, 4);
  }, [ai.enabled, issues, entities]);

  const send = (value: string) => {
    const v = value.trim();
    if (!v || busy) return;
    onSend(v);
    setText('');
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-slate-800 px-4 py-2.5 text-xs">
        {ai.enabled ? (
          <span className="flex items-center gap-1.5 font-medium text-violet-300"><Sparkles className="h-3.5 w-3.5" /> Groq · <span className="font-mono">{ai.model}</span></span>
        ) : (
          <span className="flex items-center gap-1.5 font-medium text-slate-400" title="Set GROQ_API_KEY in backend/.env for natural-language editing">
            <Terminal className="h-3.5 w-3.5" /> Offline command mode — set GROQ_API_KEY for full AI
          </span>
        )}
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto p-4 text-sm">
        {messages.length === 0 && (
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-slate-300">
            <div className="mb-2 flex items-center gap-2 font-semibold text-white"><Bot className="h-4 w-4 text-blue-400" /> Drawing assistant</div>
            <p className="leading-relaxed text-slate-400">
              Ask me to explain a finding or change the drawing — rename tags, insert valves, add and connect instruments,
              move symbols, fill in the title block. Every change I make becomes a revision you can undo.
            </p>
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[88%] rounded-2xl px-3.5 py-2.5 leading-relaxed ${m.role === 'user' ? 'rounded-br-md bg-blue-600 text-white' : 'rounded-bl-md border border-slate-800 bg-slate-900 text-slate-200'}`}>
              <RichText text={m.content} />
              {m.actions.length > 0 && (
                <div className="mt-2.5 space-y-1 border-t border-slate-800 pt-2">
                  {m.actions.map((a, i) => (
                    <div key={i} className="flex items-start gap-1.5 text-xs text-emerald-300/90"><Wrench className="mt-0.5 h-3 w-3 shrink-0" />{a}</div>
                  ))}
                  {m.rev_no && (
                    <button onClick={() => onJumpToRevision(m.rev_no!)} className="mt-1 flex items-center gap-1 text-[11px] font-medium text-slate-400 hover:text-white">
                      <History className="h-3 w-3" /> Saved as revision {m.rev_no}
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
        {busy && (
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin text-blue-400" /> {ai.enabled ? 'Thinking and editing the drawing…' : 'Working…'}
          </div>
        )}
        <div ref={endRef} />
      </div>

      <div className="space-y-2 border-t border-slate-800 p-3">
        <div className="flex flex-wrap gap-1.5">
          {suggestions.map((s) => (
            <button key={s} disabled={busy} onClick={() => send(s)}
              className="rounded-full border border-slate-700 bg-slate-900 px-2.5 py-1 text-left text-[11px] text-slate-300 transition hover:border-blue-500/60 hover:text-white disabled:opacity-40">
              {s}
            </button>
          ))}
        </div>
        <div className="flex items-end gap-2 rounded-xl border border-slate-700 bg-slate-950 p-2 focus-within:border-blue-500">
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} disabled={busy}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                send(text);
              }
            }}
            placeholder={ai.enabled ? 'e.g. "Add a check valve after the standby pump and renumber it P-102"' : 'Type a command, or "help"'}
            className="max-h-32 flex-1 resize-none bg-transparent px-1 text-sm text-white placeholder-slate-600 outline-none" />
          <button onClick={() => send(text)} disabled={busy || !text.trim()} title="Send (Enter)"
            className="rounded-lg bg-blue-600 p-2 text-white transition hover:bg-blue-500 disabled:bg-slate-800 disabled:text-slate-600">
            <CornerDownLeft className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
