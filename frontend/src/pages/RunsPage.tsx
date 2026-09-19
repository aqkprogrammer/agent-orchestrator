import { History } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { PageHeader } from "../components/PageHeader";
import { Card, EmptyState, Spinner, StatusBadge } from "../components/ui";
import { api } from "../lib/api";
import { compact, ms, timeAgo } from "../lib/format";
import { usePolling } from "../lib/hooks";
import { useUser } from "../lib/user";

const FILTERS = ["", "running", "awaiting_approval", "completed", "failed"];

export function RunsPage() {
  const { userId } = useUser();
  const navigate = useNavigate();
  const [status, setStatus] = useState("");
  const runs = usePolling(() => api.listRuns({ user_id: userId, status: status || undefined, limit: 100 }), 5000, [userId, status]);

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Run history"
        subtitle="Every run, with token usage, tool calls and wall-clock latency. Click a run for its full trace."
        actions={
          <select value={status} onChange={(e) => setStatus(e.target.value)} className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm">
            {FILTERS.map((f) => (
              <option key={f} value={f}>
                {f ? f.replace("_", " ") : "All statuses"}
              </option>
            ))}
          </select>
        }
      />
      <div className="scrollbar-thin flex-1 overflow-y-auto px-8 py-6">
        {runs.loading && !runs.data && <Spinner className="mx-auto h-6 w-6" />}
        {runs.data?.length === 0 && (
          <EmptyState icon={<History className="h-5 w-5" />} title="No runs yet">
            Start a task from the console.
          </EmptyState>
        )}
        {runs.data && runs.data.length > 0 && (
          <Card className="overflow-hidden">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Task</th>
                  <th className="px-4 py-2.5 font-medium">Status</th>
                  <th className="px-4 py-2.5 text-right font-medium">Tokens</th>
                  <th className="px-4 py-2.5 text-right font-medium">LLM / tools</th>
                  <th className="px-4 py-2.5 text-right font-medium">Latency</th>
                  <th className="px-4 py-2.5 text-right font-medium">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {runs.data.map((run) => (
                  <tr key={run.id} onClick={() => navigate(`/runs/${run.id}`)} className="cursor-pointer hover:bg-slate-50">
                    <td className="max-w-md truncate px-4 py-3 text-slate-800">{run.task}</td>
                    <td className="px-4 py-3">
                      <StatusBadge status={run.status} />
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs text-slate-600">{compact(run.input_tokens + run.output_tokens)}</td>
                    <td className="px-4 py-3 text-right font-mono text-xs text-slate-600">
                      {run.llm_calls} / {run.tool_calls}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs text-slate-600">{ms(run.latency_ms)}</td>
                    <td className="px-4 py-3 text-right text-xs text-slate-400">{timeAgo(run.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </div>
    </div>
  );
}
