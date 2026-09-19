import clsx from "clsx";
import { Activity, ArrowUp, Bot, ExternalLink, MessagesSquare, Plus, Radio, Sparkles, User } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { ApprovalCard } from "../components/ApprovalCard";
import { Timeline } from "../components/Timeline";
import { Answer, Badge, Button, EmptyState, Spinner, StatusBadge } from "../components/ui";
import { api } from "../lib/api";
import { compact, ms, timeAgo } from "../lib/format";
import { usePolling, useRunStream } from "../lib/hooks";
import type { Run, RunEvent } from "../lib/types";
import { useUser } from "../lib/user";

const EXAMPLES = [
  {
    label: "Refund + email (needs approval)",
    task: "My name is Dana and I prefer concise answers. Order ORD-1042 arrived damaged - please refund $250 and email me at dana@example.com to confirm.",
  },
  { label: "Math + research", task: "Calculate 15% of 2,340 and add 12 * 49. Also, what does the Pro plan include?" },
  { label: "Policy summary", task: "Research our refund and escalation policy and write a short summary for the support team." },
  { label: "Escalate to a manager", task: "I want to speak to a manager about my cancelled order ORD-1003." },
  { label: "Low confidence review", task: "Forecast next quarter's churn for the Pro plan." },
  { label: "Memory recall", task: "Write a short welcome note for me." },
];

const REFRESH_ON = new Set(["run_started", "approval_requested", "approval_resolved", "run_completed", "run_failed"]);
const ACTIVE = new Set(["queued", "running", "awaiting_approval"]);

export function ConsolePage() {
  const { userId } = useUser();
  const [params, setParams] = useSearchParams();
  const threadId = params.get("thread");
  const [selection, setSelection] = useState<{ threadId: string | null; runId: string } | null>(null);
  const [task, setTask] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showLlm, setShowLlm] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const timelineRef = useRef<HTMLDivElement>(null);

  const threads = usePolling(() => api.listThreads(userId), 10000, [userId]);
  const thread = usePolling(
    () => (threadId ? api.getThread(threadId) : Promise.resolve(null)),
    0,
    [threadId],
  );
  const approvals = usePolling(() => api.listApprovals({ status: "pending", user_id: userId }), 5000, [userId]);

  const runs = useMemo(() => thread.data?.runs ?? [], [thread.data]);
  const selectedRun = selection && selection.threadId === threadId ? selection.runId : null;
  const activeRunId = selectedRun ?? runs.at(-1)?.id ?? null;
  const activeRun = runs.find((r) => r.id === activeRunId) ?? null;
  const busyRun = runs.find((r) => ACTIVE.has(r.status));

  const { reload: reloadThread } = thread;
  const { reload: reloadThreads } = threads;
  const { reload: reloadApprovals } = approvals;
  const onEvent = useCallback(
    (event: RunEvent) => {
      if (REFRESH_ON.has(event.type)) {
        void reloadThread();
        void reloadApprovals();
        if (event.type === "run_completed") void reloadThreads();
      }
    },
    [reloadThread, reloadThreads, reloadApprovals],
  );
  const { events, connected } = useRunStream(activeRunId, onEvent);

  useEffect(() => {
    const el = timelineRef.current;
    if (el && connected) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [events.length, connected]);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [runs.length, activeRun?.status]);

  const submit = async (text: string) => {
    const clean = text.trim();
    if (!clean || sending) return;
    setSending(true);
    setError(null);
    try {
      const run = await api.createRun(clean, userId, threadId);
      setTask("");
      setSelection({ threadId: run.thread_id, runId: run.id });
      if (run.thread_id !== threadId) setParams({ thread: run.thread_id });
      else void reloadThread();
      void reloadThreads();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSending(false);
    }
  };

  const pendingFor = (run: Run) => approvals.data?.find((a) => a.run_id === run.id && a.status === "pending");

  return (
    <div className="flex h-full">
      {/* threads */}
      <section className="flex w-64 shrink-0 flex-col border-r border-slate-200 bg-white/60">
        <div className="p-3">
          <Button variant="secondary" className="w-full" onClick={() => setParams({})}>
            <Plus className="h-4 w-4" /> New conversation
          </Button>
        </div>
        <div className="scrollbar-thin flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">
          {threads.data?.length === 0 && <p className="px-3 py-6 text-center text-xs text-slate-400">No conversations yet.</p>}
          {threads.data?.map((t) => (
            <button
              key={t.id}
              onClick={() => setParams({ thread: t.id })}
              className={clsx(
                "w-full rounded-lg px-3 py-2 text-left transition",
                t.id === threadId ? "bg-indigo-50 ring-1 ring-inset ring-indigo-200" : "hover:bg-slate-100",
              )}
            >
              <div className="truncate text-sm font-medium text-slate-700">{t.title}</div>
              <div className="text-[11px] text-slate-400">{timeAgo(t.updated_at)}</div>
            </button>
          ))}
        </div>
      </section>

      {/* conversation */}
      <section className="flex min-w-0 flex-1 flex-col">
        <div className="scrollbar-thin flex-1 overflow-y-auto">
          {!threadId ? (
            <div className="mx-auto max-w-2xl px-6 py-16">
              <div className="mb-8 text-center">
                <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-indigo-600 text-white shadow-lg shadow-indigo-200">
                  <Sparkles className="h-6 w-6" />
                </div>
                <h1 className="text-2xl font-semibold tracking-tight text-slate-900">What should the team work on?</h1>
                <p className="mt-2 text-sm text-slate-500">
                  A supervisor delegates to a researcher, analyst, ops agent and writer. Sensitive actions pause for your approval.
                </p>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                {EXAMPLES.map((ex) => (
                  <button
                    key={ex.label}
                    onClick={() => void submit(ex.task)}
                    disabled={sending}
                    className="rounded-xl border border-slate-200 bg-white p-3 text-left shadow-sm transition hover:border-indigo-300 hover:shadow disabled:opacity-50"
                  >
                    <div className="text-sm font-medium text-slate-800">{ex.label}</div>
                    <div className="mt-1 line-clamp-2 text-xs text-slate-500">{ex.task}</div>
                  </button>
                ))}
              </div>
            </div>
          ) : thread.loading && !thread.data ? (
            <div className="flex justify-center py-20">
              <Spinner className="h-6 w-6" />
            </div>
          ) : (
            <div className="mx-auto max-w-3xl space-y-6 px-6 py-8">
              {runs.map((run) => {
                const pending = pendingFor(run);
                return (
                  <div key={run.id} className="space-y-3">
                    <div className="flex justify-end gap-3">
                      <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-indigo-600 px-4 py-2.5 text-sm text-white shadow-sm">{run.task}</div>
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-200 text-slate-500">
                        <User className="h-4 w-4" />
                      </div>
                    </div>
                    <div className="flex gap-3">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-indigo-600">
                        <Bot className="h-4 w-4" />
                      </div>
                      <div
                        onClick={() => setSelection({ threadId, runId: run.id })}
                        className={clsx(
                          "min-w-0 flex-1 cursor-pointer space-y-3 rounded-2xl rounded-tl-sm border bg-white px-4 py-3 shadow-sm transition",
                          run.id === activeRunId ? "border-indigo-300 ring-2 ring-indigo-100" : "border-slate-200 hover:border-slate-300",
                        )}
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <StatusBadge status={run.status} />
                          {run.confidence !== null && <Badge tone={run.confidence >= 0.55 ? "green" : "amber"}>confidence {run.confidence.toFixed(2)}</Badge>}
                          <span className="text-xs text-slate-400">
                            {compact(run.input_tokens + run.output_tokens)} tokens · {run.tool_calls} tools · {ms(run.latency_ms)}
                          </span>
                          <Link to={`/runs/${run.id}`} onClick={(e) => e.stopPropagation()} className="ml-auto inline-flex items-center gap-1 text-xs text-indigo-600 hover:underline">
                            trace <ExternalLink className="h-3 w-3" />
                          </Link>
                        </div>
                        {run.final_answer && <Answer text={run.final_answer} />}
                        {run.status === "failed" && <p className="text-sm text-red-600">{run.error}</p>}
                        {(run.status === "running" || run.status === "queued") && (
                          <p className="flex items-center gap-2 text-sm text-slate-500">
                            <Spinner /> Agents are working...
                          </p>
                        )}
                        {pending && (
                          <div onClick={(e) => e.stopPropagation()}>
                            <ApprovalCard
                              approval={pending}
                              compact
                              onDecided={() => {
                                void reloadApprovals();
                                void reloadThread();
                              }}
                            />
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
              <div ref={bottomRef} />
            </div>
          )}
        </div>

        {/* composer */}
        <div className="border-t border-slate-200 bg-white px-6 py-4">
          <form
            className="mx-auto flex max-w-3xl items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              void submit(task);
            }}
          >
            <textarea
              value={task}
              onChange={(e) => setTask(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void submit(task);
                }
              }}
              rows={2}
              maxLength={4000}
              disabled={Boolean(busyRun)}
              placeholder={busyRun ? "Waiting for the current run to finish..." : threadId ? "Continue the conversation..." : "Describe a task for the agents..."}
              className="min-h-[3rem] flex-1 resize-none rounded-xl border border-slate-300 px-4 py-3 text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-100 disabled:bg-slate-50"
            />
            <Button type="submit" className="h-12 w-12 rounded-xl" loading={sending} disabled={!task.trim() || Boolean(busyRun)} aria-label="Send">
              {!sending && <ArrowUp className="h-5 w-5" />}
            </Button>
          </form>
          {error && <p className="mx-auto mt-2 max-w-3xl text-xs text-red-600">{error}</p>}
        </div>
      </section>

      {/* live timeline */}
      <aside className="hidden w-[400px] shrink-0 flex-col border-l border-slate-200 bg-white xl:flex">
        <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-3">
          <Activity className="h-4 w-4 text-indigo-600" />
          <h2 className="text-sm font-semibold text-slate-800">Agent timeline</h2>
          {connected && (
            <span className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-600">
              <Radio className="h-3 w-3 animate-pulse-dot" /> live
            </span>
          )}
          <label className="ml-auto flex items-center gap-1.5 text-[11px] text-slate-500">
            <input type="checkbox" checked={showLlm} onChange={(e) => setShowLlm(e.target.checked)} className="accent-indigo-600" />
            LLM calls
          </label>
        </div>
        <div ref={timelineRef} className="scrollbar-thin flex-1 overflow-y-auto p-4">
          {activeRunId ? (
            events.length ? <Timeline events={events} showLlm={showLlm} /> : <div className="flex justify-center py-10"><Spinner /></div>
          ) : (
            <EmptyState icon={<MessagesSquare className="h-5 w-5" />} title="No run selected">
              Start a task to watch the supervisor delegate, tools execute and approvals appear in real time.
            </EmptyState>
          )}
        </div>
      </aside>
    </div>
  );
}
