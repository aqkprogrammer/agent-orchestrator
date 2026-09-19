import { ArrowLeft, ScrollText } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApprovalCard } from "../components/ApprovalCard";
import { Timeline } from "../components/Timeline";
import { AgentBadge, Answer, Badge, Card, Collapsible, JsonBlock, Spinner, Stat, StatusBadge } from "../components/ui";
import { api } from "../lib/api";
import { clockTime, compact, ms } from "../lib/format";
import { usePolling, useRunStream } from "../lib/hooks";
import type { RunEvent } from "../lib/types";

interface AgentUsage {
  agent: string;
  calls: number;
  input: number;
  output: number;
  latency: number;
}

export function RunDetailPage() {
  const { runId = "" } = useParams();
  const [showLlm, setShowLlm] = useState(true);
  const run = usePolling(() => api.getRun(runId), 0, [runId]);
  const audit = usePolling(() => api.runAudit(runId), 0, [runId]);

  const { reload: reloadRun } = run;
  const { reload: reloadAudit } = audit;
  const onEvent = useCallback(
    (event: RunEvent) => {
      if (["tool_result", "approval_requested", "run_completed", "run_failed", "approval_resolved"].includes(event.type)) {
        void reloadRun();
        void reloadAudit();
      }
    },
    [reloadRun, reloadAudit],
  );
  const { events } = useRunStream(runId, onEvent);

  const usage = useMemo(() => {
    const byAgent = new Map<string, AgentUsage>();
    for (const e of events) {
      if (e.type !== "llm_call") continue;
      const agent = e.agent ?? "system";
      const row = byAgent.get(agent) ?? { agent, calls: 0, input: 0, output: 0, latency: 0 };
      row.calls += 1;
      row.input += Number(e.data.input_tokens ?? 0);
      row.output += Number(e.data.output_tokens ?? 0);
      row.latency += Number(e.data.latency_ms ?? 0);
      byAgent.set(agent, row);
    }
    return [...byAgent.values()];
  }, [events]);

  const r = run.data;
  if (run.error) return <p className="p-8 text-sm text-red-600">{run.error}</p>;
  if (!r) return <Spinner className="m-8 h-6 w-6" />;

  return (
    <div className="scrollbar-thin h-full overflow-y-auto">
      <div className="border-b border-slate-200 bg-white px-8 py-6">
        <Link to="/runs" className="mb-3 inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-800">
          <ArrowLeft className="h-3.5 w-3.5" /> Run history
        </Link>
        <div className="flex flex-wrap items-start gap-3">
          <h1 className="max-w-3xl flex-1 text-lg font-semibold text-slate-900">{r.task}</h1>
          <StatusBadge status={r.status} />
        </div>
        <p className="mt-1 font-mono text-[11px] text-slate-400">
          run {r.id} · thread{" "}
          <Link to={`/?thread=${r.thread_id}`} className="text-indigo-600 hover:underline">
            {r.thread_id}
          </Link>
        </p>
        <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="Model" value={<span className="font-mono text-xs">{r.llm_provider}/{r.model}</span>} />
          <Stat label="Input tokens" value={compact(r.input_tokens)} />
          <Stat label="Output tokens" value={compact(r.output_tokens)} />
          <Stat label="LLM calls" value={r.llm_calls} />
          <Stat label="Tool calls" value={r.tool_calls} />
          <Stat label="Wall time" value={ms(r.latency_ms)} />
        </div>
      </div>

      <div className="grid gap-6 px-8 py-6 xl:grid-cols-[minmax(0,1fr)_420px]">
        <div className="space-y-6">
          {r.pending_approval && (
            <ApprovalCard
              approval={r.pending_approval}
              compact
              onDecided={() => {
                void reloadRun();
              }}
            />
          )}
          {r.final_answer && (
            <Card className="p-5">
              <div className="mb-3 flex items-center gap-2">
                <h2 className="text-sm font-semibold text-slate-800">Final answer</h2>
                {r.confidence !== null && <Badge tone={r.confidence >= 0.55 ? "green" : "amber"}>confidence {r.confidence.toFixed(2)}</Badge>}
              </div>
              <Answer text={r.final_answer} />
            </Card>
          )}
          {r.error && (
            <Card className="border-red-200 p-5">
              <h2 className="mb-1 text-sm font-semibold text-red-700">Error</h2>
              <p className="font-mono text-xs text-red-600">{r.error}</p>
            </Card>
          )}
          <Card className="p-5">
            <div className="mb-4 flex items-center gap-2">
              <h2 className="text-sm font-semibold text-slate-800">Execution trace</h2>
              <span className="text-xs text-slate-400">{events.length} events</span>
              <label className="ml-auto flex items-center gap-1.5 text-xs text-slate-500">
                <input type="checkbox" checked={showLlm} onChange={(e) => setShowLlm(e.target.checked)} className="accent-indigo-600" />
                show LLM calls
              </label>
            </div>
            {events.length ? <Timeline events={events} showLlm={showLlm} /> : <Spinner />}
          </Card>
        </div>

        <div className="space-y-6">
          <Card className="p-5">
            <h2 className="mb-3 text-sm font-semibold text-slate-800">Usage by agent</h2>
            <table className="w-full text-xs">
              <thead className="text-left text-[11px] uppercase tracking-wide text-slate-400">
                <tr>
                  <th className="pb-2 font-medium">Agent</th>
                  <th className="pb-2 text-right font-medium">Calls</th>
                  <th className="pb-2 text-right font-medium">In / out</th>
                  <th className="pb-2 text-right font-medium">Latency</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {usage.map((u) => (
                  <tr key={u.agent}>
                    <td className="py-2">
                      <AgentBadge agent={u.agent} />
                    </td>
                    <td className="py-2 text-right font-mono">{u.calls}</td>
                    <td className="py-2 text-right font-mono">
                      {compact(u.input)} / {compact(u.output)}
                    </td>
                    <td className="py-2 text-right font-mono">{ms(u.latency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>

          <Card className="p-5">
            <div className="mb-3 flex items-center gap-2">
              <ScrollText className="h-4 w-4 text-slate-500" />
              <h2 className="text-sm font-semibold text-slate-800">Tool audit log</h2>
            </div>
            {audit.data?.length === 0 && <p className="text-xs text-slate-400">No tool calls.</p>}
            <ul className="space-y-3">
              {audit.data?.map((a) => (
                <li key={a.id} className="rounded-lg border border-slate-100 p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs font-medium text-slate-800">{a.action}</span>
                    <Badge tone={a.status === "error" || a.status === "rejected" ? "red" : a.status === "approved" ? "indigo" : "green"}>{a.status}</Badge>
                    <AgentBadge agent={a.agent} />
                    <span className="ml-auto font-mono text-[11px] text-slate-400">
                      {clockTime(a.created_at)} · {ms(a.latency_ms)}
                    </span>
                  </div>
                  <div className="mt-2 space-y-1">
                    <Collapsible label="input">
                      <JsonBlock value={a.args} />
                    </Collapsible>
                    <Collapsible label="output">
                      <JsonBlock value={a.result} />
                    </Collapsible>
                  </div>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </div>
  );
}
