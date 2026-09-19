import clsx from "clsx";
import { Brain, History, Inbox, MessagesSquare, Network, UserRound } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { api } from "../lib/api";
import { usePolling } from "../lib/hooks";
import type { AppConfig } from "../lib/types";
import { useUser } from "../lib/user";

const NAV = [
  { to: "/", label: "Console", icon: MessagesSquare, end: true },
  { to: "/approvals", label: "Approvals", icon: Inbox },
  { to: "/memory", label: "Memory", icon: Brain },
  { to: "/runs", label: "Run history", icon: History },
];

export function Layout() {
  const { userId, setUserId } = useUser();
  const [config, setConfig] = useState<AppConfig | null>(null);
  const pending = usePolling(() => api.listApprovals({ status: "pending" }), 4000, []);
  const health = usePolling(() => api.health(), 15000, []);

  useEffect(() => {
    api.config().then(setConfig).catch(() => setConfig(null));
  }, []);

  const pendingCount = pending.data?.length ?? 0;
  const healthy = health.data?.status === "ok" && !health.error;

  return (
    <div className="flex h-full">
      <aside className="flex w-60 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <div className="rounded-lg bg-indigo-600 p-1.5 text-white shadow-sm">
            <Network className="h-5 w-5" />
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-900">Agent Orchestrator</div>
            <div className="text-[11px] text-slate-400">LangGraph · HITL · Memory</div>
          </div>
        </div>
        <nav className="space-y-0.5 px-3">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                clsx(
                  "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition",
                  isActive ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-slate-50 hover:text-slate-900",
                )
              }
            >
              <Icon className="h-4 w-4" />
              {label}
              {to === "/approvals" && pendingCount > 0 && (
                <span className="ml-auto rounded-full bg-amber-500 px-1.5 py-0.5 text-[10px] font-bold text-white">
                  {pendingCount}
                </span>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="mt-auto space-y-3 border-t border-slate-100 p-4">
          <label className="block">
            <span className="mb-1 flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-slate-400">
              <UserRound className="h-3 w-3" /> Acting as user
            </span>
            <input
              key={userId}
              defaultValue={userId}
              onBlur={(e) => setUserId(e.currentTarget.value)}
              onKeyDown={(e) => e.key === "Enter" && setUserId(e.currentTarget.value)}
              className="w-full rounded-lg border border-slate-300 px-2.5 py-1.5 font-mono text-xs focus:border-indigo-500 focus:outline-none"
            />
          </label>
          <div className="space-y-1 text-[11px] text-slate-500">
            <div className="flex items-center gap-1.5">
              <span className={clsx("h-2 w-2 rounded-full", healthy ? "bg-emerald-500" : "bg-red-500")} />
              {healthy ? "All systems ready" : "Backend degraded"}
            </div>
            {config && (
              <>
                <div>
                  Model: <span className="font-mono text-slate-700">{config.llm.provider}/{config.llm.model}</span>
                </div>
                <div>
                  Executor: <span className="font-mono text-slate-700">{config.infrastructure.executor}</span> · bus{" "}
                  <span className="font-mono text-slate-700">{config.infrastructure.event_bus}</span>
                </div>
              </>
            )}
          </div>
        </div>
      </aside>
      <main className="min-w-0 flex-1 overflow-hidden">
        <Outlet />
      </main>
    </div>
  );
}
