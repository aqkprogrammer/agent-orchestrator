export const AGENT_STYLES: Record<string, { label: string; dot: string; chip: string }> = {
  supervisor: { label: "Supervisor", dot: "bg-violet-500", chip: "bg-violet-50 text-violet-700 ring-violet-200" },
  researcher: { label: "Researcher", dot: "bg-sky-500", chip: "bg-sky-50 text-sky-700 ring-sky-200" },
  analyst: { label: "Analyst", dot: "bg-emerald-500", chip: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
  ops: { label: "Ops", dot: "bg-amber-500", chip: "bg-amber-50 text-amber-800 ring-amber-200" },
  writer: { label: "Writer", dot: "bg-rose-500", chip: "bg-rose-50 text-rose-700 ring-rose-200" },
  finalizer: { label: "Finalizer", dot: "bg-indigo-500", chip: "bg-indigo-50 text-indigo-700 ring-indigo-200" },
  memory: { label: "Memory", dot: "bg-teal-500", chip: "bg-teal-50 text-teal-700 ring-teal-200" },
};

const FALLBACK_AGENT = { label: "System", dot: "bg-slate-400", chip: "bg-slate-100 text-slate-600 ring-slate-200" };

export function agentStyle(agent: string | null | undefined) {
  return (agent && AGENT_STYLES[agent]) || FALLBACK_AGENT;
}
