import clsx from "clsx";
import { ChevronRight, Loader2 } from "lucide-react";
import { useState, type ButtonHTMLAttributes, type ReactNode } from "react";

import { agentStyle } from "../lib/agents";
import type { RunStatus } from "../lib/types";

export function AgentBadge({ agent }: { agent: string | null | undefined }) {
  const style = agentStyle(agent);
  return (
    <span className={clsx("inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset", style.chip)}>
      <span className={clsx("h-1.5 w-1.5 rounded-full", style.dot)} />
      {agent ? style.label : "System"}
    </span>
  );
}

const STATUS_STYLES: Record<RunStatus, string> = {
  queued: "bg-slate-100 text-slate-600 ring-slate-200",
  running: "bg-blue-50 text-blue-700 ring-blue-200",
  awaiting_approval: "bg-amber-50 text-amber-800 ring-amber-300",
  completed: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  failed: "bg-red-50 text-red-700 ring-red-200",
};

const STATUS_LABEL: Record<RunStatus, string> = {
  queued: "Queued",
  running: "Running",
  awaiting_approval: "Needs approval",
  completed: "Completed",
  failed: "Failed",
};

export function StatusBadge({ status }: { status: RunStatus }) {
  const live = status === "running" || status === "queued";
  return (
    <span className={clsx("inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset", STATUS_STYLES[status])}>
      {live && <span className="h-1.5 w-1.5 rounded-full bg-current animate-pulse-dot" />}
      {STATUS_LABEL[status]}
    </span>
  );
}

export function Badge({ children, tone = "slate" }: { children: ReactNode; tone?: "slate" | "amber" | "red" | "green" | "indigo" }) {
  const tones = {
    slate: "bg-slate-100 text-slate-600 ring-slate-200",
    amber: "bg-amber-50 text-amber-800 ring-amber-200",
    red: "bg-red-50 text-red-700 ring-red-200",
    green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    indigo: "bg-indigo-50 text-indigo-700 ring-indigo-200",
  };
  return (
    <span className={clsx("inline-flex items-center rounded-md px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset", tones[tone])}>
      {children}
    </span>
  );
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger" | "ghost" | "success";
  size?: "sm" | "md";
  loading?: boolean;
};

export function Button({ variant = "primary", size = "md", loading, className, children, disabled, ...rest }: ButtonProps) {
  const variants = {
    primary: "bg-indigo-600 text-white hover:bg-indigo-500 shadow-sm",
    success: "bg-emerald-600 text-white hover:bg-emerald-500 shadow-sm",
    secondary: "bg-white text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50 shadow-sm",
    danger: "bg-white text-red-600 ring-1 ring-inset ring-red-200 hover:bg-red-50",
    ghost: "text-slate-600 hover:bg-slate-100",
  };
  const sizes = { sm: "px-2.5 py-1 text-xs", md: "px-3.5 py-2 text-sm" };
  return (
    <button
      className={clsx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 disabled:cursor-not-allowed disabled:opacity-50",
        variants[variant],
        sizes[size],
        className,
      )}
      disabled={disabled || loading}
      {...rest}
    >
      {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
      {children}
    </button>
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={clsx("rounded-xl border border-slate-200 bg-white shadow-sm", className)}>{children}</div>;
}

export function EmptyState({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="mb-3 rounded-full bg-slate-100 p-3 text-slate-400">{icon}</div>
      <p className="font-medium text-slate-700">{title}</p>
      {children && <div className="mt-1 max-w-sm text-sm text-slate-500">{children}</div>}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={clsx("h-4 w-4 animate-spin text-slate-400", className)} />;
}

export function JsonBlock({ value, className }: { value: unknown; className?: string }) {
  return (
    <pre className={clsx("scrollbar-thin max-h-72 overflow-auto rounded-lg bg-slate-900 p-3 font-mono text-[11.5px] leading-relaxed text-slate-100", className)}>
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export function Collapsible({ label, children, defaultOpen = false }: { label: ReactNode; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-700"
      >
        <ChevronRight className={clsx("h-3.5 w-3.5 transition-transform", open && "rotate-90")} />
        {label}
      </button>
      {open && <div className="mt-2">{children}</div>}
    </div>
  );
}

/** Minimal, safe markdown: paragraphs, bullet lists and **bold** (no HTML injection). */
export function Answer({ text }: { text: string }) {
  const blocks = text.split(/\n{2,}/);
  const inline = (line: string) =>
    line.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
      part.startsWith("**") && part.endsWith("**") ? (
        <strong key={i} className="font-semibold text-slate-900">
          {part.slice(2, -2)}
        </strong>
      ) : (
        <span key={i}>{part}</span>
      ),
    );
  return (
    <div className="space-y-3 text-sm leading-relaxed text-slate-700">
      {blocks.map((block, bi) => {
        const lines = block.split("\n");
        const bullets = lines.filter((l) => l.startsWith("- "));
        const head = lines.filter((l) => !l.startsWith("- "));
        return (
          <div key={bi}>
            {head.map((line, li) => (
              <p key={li}>{inline(line)}</p>
            ))}
            {bullets.length > 0 && (
              <ul className="mt-1 list-disc space-y-1 pl-5 marker:text-slate-400">
                {bullets.map((line, li) => (
                  <li key={li}>{inline(line.slice(2))}</li>
                ))}
              </ul>
            )}
          </div>
        );
      })}
    </div>
  );
}

export function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2 ring-1 ring-inset ring-slate-200">
      <div className="text-[11px] font-medium uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-0.5 text-sm font-semibold text-slate-800">{value}</div>
    </div>
  );
}
