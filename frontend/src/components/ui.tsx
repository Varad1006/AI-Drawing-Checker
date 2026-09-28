import { useEffect, useRef, useState, type ReactNode } from 'react';
import { CircleCheck, Info, TriangleAlert, X } from 'lucide-react';
import type { IssueStatus, Severity } from '../types';
import type { ToastEvent } from '../lib/toast';

const SEV_STYLE: Record<Severity, string> = {
  CRITICAL: 'bg-rose-500/15 text-rose-300 ring-rose-500/40',
  HIGH: 'bg-orange-500/15 text-orange-300 ring-orange-500/40',
  MEDIUM: 'bg-yellow-500/15 text-yellow-200 ring-yellow-500/40',
  LOW: 'bg-sky-500/15 text-sky-300 ring-sky-500/40',
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold tracking-wider ring-1 ${SEV_STYLE[severity]}`}>
      {severity}
    </span>
  );
}

const STATUS_STYLE: Record<IssueStatus, string> = {
  OPEN: 'text-slate-400',
  ACCEPTED: 'text-amber-300',
  REJECTED: 'text-slate-500 line-through',
  FIXED: 'text-emerald-400',
};

export function StatusText({ status }: { status: IssueStatus }) {
  return <span className={`text-[10px] font-semibold uppercase tracking-wider ${STATUS_STYLE[status]}`}>{status.toLowerCase()}</span>;
}

export function Menu({ button, children, align = 'right' }: { button: (open: boolean) => ReactNode; children: (close: () => void) => ReactNode; align?: 'left' | 'right' }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);
  return (
    <div ref={ref} className="relative">
      <div onClick={() => setOpen((o) => !o)}>{button(open)}</div>
      {open && (
        <div className={`absolute top-full z-50 mt-2 min-w-56 overflow-hidden rounded-xl border border-slate-700 bg-slate-900 shadow-2xl shadow-black/50 ${align === 'right' ? 'right-0' : 'left-0'}`}>
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}

export function MenuItem({ icon, label, hint, onClick, disabled }: { icon?: ReactNode; label: ReactNode; hint?: ReactNode; onClick: () => void; disabled?: boolean }) {
  return (
    <button onClick={onClick} disabled={disabled}
      className="flex w-full items-start gap-3 px-3 py-2.5 text-left text-sm text-slate-200 transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40">
      {icon && <span className="mt-0.5 text-slate-400">{icon}</span>}
      <span className="min-w-0 flex-1">
        <span className="block">{label}</span>
        {hint && <span className="mt-0.5 block text-xs text-slate-500">{hint}</span>}
      </span>
    </button>
  );
}

export function Toaster() {
  const [items, setItems] = useState<ToastEvent[]>([]);
  useEffect(() => {
    const on = (e: Event) => {
      const t = (e as CustomEvent<ToastEvent>).detail;
      setItems((xs) => [...xs.slice(-3), t]);
      setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== t.id)), t.kind === 'error' ? 7000 : 4000);
    };
    window.addEventListener('lc-toast', on);
    return () => window.removeEventListener('lc-toast', on);
  }, []);
  return (
    <div className="pointer-events-none fixed bottom-5 left-1/2 z-[100] flex -translate-x-1/2 flex-col items-center gap-2">
      {items.map((t) => (
        <div key={t.id}
          className={`pointer-events-auto flex max-w-lg items-start gap-2.5 rounded-xl border px-4 py-3 text-sm shadow-2xl shadow-black/40 backdrop-blur ${
            t.kind === 'error' ? 'border-rose-500/40 bg-rose-950/90 text-rose-100'
              : t.kind === 'success' ? 'border-emerald-500/40 bg-emerald-950/90 text-emerald-100'
              : 'border-slate-700 bg-slate-900/95 text-slate-200'}`}>
          {t.kind === 'error' ? <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />
            : t.kind === 'success' ? <CircleCheck className="mt-0.5 h-4 w-4 shrink-0" /> : <Info className="mt-0.5 h-4 w-4 shrink-0" />}
          <span className="whitespace-pre-line">{t.message}</span>
          <button className="ml-1 opacity-60 hover:opacity-100" onClick={() => setItems((xs) => xs.filter((x) => x.id !== t.id))}>
            <X className="h-4 w-4" />
          </button>
        </div>
      ))}
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="rounded border border-slate-700 bg-slate-800 px-1.5 py-0.5 font-mono text-[10px] text-slate-300">{children}</kbd>;
}
