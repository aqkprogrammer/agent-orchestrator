import clsx from "clsx";
import {
  AlertTriangle,
  ArrowRight,
  Brain,
  CheckCircle2,
  CircleDot,
  Cpu,
  Flag,
  MessageSquare,
  Play,
  RotateCcw,
  Save,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Wrench,
  XCircle,
} from "lucide-react";
import type { ReactNode } from "react";

import { clockTime, ms, titleCase } from "../lib/format";
import type { RunEvent } from "../lib/types";
import { agentStyle } from "../lib/agents";
import { AgentBadge, Badge, Collapsible, JsonBlock } from "./ui";

type Data = Record<string, unknown>;
const str = (v: unknown) => (typeof v === "string" ? v : v === undefined || v === null ? "" : String(v));
const num = (v: unknown) => (typeof v === "number" ? v : 0);

function Row({ icon, tone, title, agent, time, children }: {
  icon: ReactNode;
  tone: string;
  title: ReactNode;
  agent?: string | null;
  time?: string | null;
  children?: ReactNode;
}) {
  return (
    <li className="relative pl-9">
      <span className={clsx("absolute left-0 top-0.5 flex h-6 w-6 items-center justify-center rounded-full ring-4 ring-white", tone)}>
        {icon}
      </span>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-slate-800">{title}</span>
        {agent !== undefined && <AgentBadge agent={agent} />}
        <span className="ml-auto font-mono text-[11px] text-slate-400">{clockTime(time)}</span>
      </div>
      {children && <div className="mt-1.5 space-y-2 text-sm text-slate-600">{children}</div>}
    </li>
  );
}

function EventRow({ event, showLlm }: { event: RunEvent; showLlm: boolean }) {
  const d = event.data as Data;
  const i = "h-3.5 w-3.5";
  switch (event.type) {
    case "run_queued":
      return <Row icon={<CircleDot className={i} />} tone="bg-slate-100 text-slate-500" title="Queued" time={event.created_at} />;
    case "run_started":
      return (
        <Row icon={<Play className={i} />} tone="bg-blue-100 text-blue-600" title="Run started" time={event.created_at}>
          <span className="text-xs text-slate-500">
            {str(d.provider)} / <span className="font-mono">{str(d.model)}</span>
          </span>
        </Row>
      );
    case "run_resumed":
      return <Row icon={<RotateCcw className={i} />} tone="bg-blue-100 text-blue-600" title="Resumed from checkpoint" time={event.created_at} />;
    case "memory_recalled": {
      const memories = (d.memories as { content: string; score: number | null; reason: string }[]) ?? [];
      return (
        <Row icon={<Brain className={i} />} tone="bg-teal-100 text-teal-600" title={`Recalled ${memories.length} memor${memories.length === 1 ? "y" : "ies"}`} time={event.created_at}>
          {memories.length > 0 && (
            <ul className="space-y-1">
              {memories.map((m, idx) => (
                <li key={idx} className="flex items-start gap-2 text-xs">
                  <Badge tone={m.reason === "semantic" ? "indigo" : "slate"}>
                    {m.reason === "semantic" ? `sim ${(m.score ?? 0).toFixed(2)}` : "profile"}
                  </Badge>
                  <span>{m.content}</span>
                </li>
              ))}
            </ul>
          )}
        </Row>
      );
    }
    case "routing": {
      const next = str(d.next);
      return (
        <Row
          icon={<ArrowRight className={i} />}
          tone="bg-violet-100 text-violet-600"
          title={
            <span className="inline-flex items-center gap-1.5">
              Supervisor <ArrowRight className="h-3 w-3 text-slate-400" />
              {next === "FINISH" ? <span className="text-slate-500">finish</span> : <AgentBadge agent={next} />}
            </span>
          }
          time={event.created_at}
        >
          {str(d.reasoning) && <p className={clsx("text-xs", d.forced ? "text-amber-700" : "text-slate-500")}>{str(d.reasoning)}</p>}
        </Row>
      );
    }
    case "agent_started":
      return (
        <Row icon={<Sparkles className={i} />} tone={clsx(agentStyle(event.agent).dot, "text-white")} title="Working" agent={event.agent} time={event.created_at}>
          {str(d.instructions) && <p className="text-xs text-slate-500">{str(d.instructions)}</p>}
        </Row>
      );
    case "agent_message":
      return (
        <Row icon={<MessageSquare className={i} />} tone="bg-slate-100 text-slate-500" title={<span className="font-normal italic text-slate-600">{str(d.text)}</span>} agent={event.agent} time={event.created_at} />
      );
    case "llm_call":
      if (!showLlm) return null;
      return (
        <Row
          icon={<Cpu className={i} />}
          tone="bg-slate-100 text-slate-400"
          title={<span className="text-xs font-normal text-slate-500">LLM {str(d.purpose)}</span>}
          time={event.created_at}
        >
          <div className="flex flex-wrap gap-1.5">
            <Badge>{num(d.input_tokens)} in</Badge>
            <Badge>{num(d.output_tokens)} out</Badge>
            <Badge>{ms(num(d.latency_ms))}</Badge>
            {event.agent && <Badge>{event.agent}</Badge>}
          </div>
        </Row>
      );
    case "tool_call":
      return (
        <Row icon={<Wrench className={i} />} tone="bg-slate-200 text-slate-600" title={<span className="font-mono text-[13px]">{str(d.tool)}()</span>} agent={event.agent} time={event.created_at}>
          <Collapsible label="arguments">
            <JsonBlock value={d.args} />
          </Collapsible>
        </Row>
      );
    case "tool_result": {
      const status = str(d.status);
      const tone = status === "error" || status === "rejected" ? "red" : status === "approved" ? "indigo" : "green";
      return (
        <Row
          icon={status === "error" || status === "rejected" ? <XCircle className={i} /> : <CheckCircle2 className={i} />}
          tone={status === "error" || status === "rejected" ? "bg-red-100 text-red-600" : "bg-emerald-100 text-emerald-600"}
          title={
            <span className="inline-flex items-center gap-2">
              <span className="font-mono text-[13px]">{str(d.tool)}</span>
              <Badge tone={tone}>{status}</Badge>
              {d.latency_ms !== undefined && <span className="text-xs font-normal text-slate-400">{ms(num(d.latency_ms))}</span>}
            </span>
          }
          time={event.created_at}
        >
          <Collapsible label="output">
            <JsonBlock value={d.output} />
          </Collapsible>
        </Row>
      );
    }
    case "approval_requested":
      return (
        <Row icon={<ShieldAlert className={i} />} tone="bg-amber-100 text-amber-700" title={`Approval required: ${d.tool ? str(d.tool) : titleCase(str(d.kind))}`} agent={event.agent} time={event.created_at}>
          <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900 ring-1 ring-inset ring-amber-200">{str(d.reason)}</p>
        </Row>
      );
    case "approval_resolved":
      return (
        <Row icon={<ShieldCheck className={i} />} tone="bg-indigo-100 text-indigo-600" title={`Human decision: ${str(d.decision)}`} time={event.created_at}>
          <p className="text-xs text-slate-500">
            by {str(d.reviewer)}
            {str(d.comment) && <> - "{str(d.comment)}"</>}
          </p>
        </Row>
      );
    case "agent_completed":
      return (
        <Row icon={<CheckCircle2 className={i} />} tone={clsx(agentStyle(event.agent).dot, "text-white")} title="Done" agent={event.agent} time={event.created_at}>
          <Collapsible label={`result (${num(d.tool_calls)} tool call${num(d.tool_calls) === 1 ? "" : "s"})`}>
            <pre className="whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-xs text-slate-700 ring-1 ring-inset ring-slate-200">{str(d.output)}</pre>
          </Collapsible>
        </Row>
      );
    case "final_answer":
      return (
        <Row icon={<Flag className={i} />} tone="bg-indigo-100 text-indigo-600" title="Final answer drafted" time={event.created_at}>
          <Badge tone={num(d.confidence) >= 0.55 ? "green" : "amber"}>confidence {num(d.confidence).toFixed(2)}</Badge>
        </Row>
      );
    case "memory_saved": {
      const saved = (d.memories as { content: string }[]) ?? [];
      return (
        <Row icon={<Save className={i} />} tone="bg-teal-100 text-teal-600" title={saved.length ? `Saved ${saved.length} new memor${saved.length === 1 ? "y" : "ies"}` : "No new memories"} time={event.created_at}>
          {saved.length > 0 && (
            <ul className="list-disc pl-4 text-xs">
              {saved.map((m, idx) => (
                <li key={idx}>{m.content}</li>
              ))}
            </ul>
          )}
        </Row>
      );
    }
    case "run_completed":
      return <Row icon={<CheckCircle2 className={i} />} tone="bg-emerald-500 text-white" title="Run completed" time={event.created_at} />;
    case "run_failed":
      return (
        <Row icon={<XCircle className={i} />} tone="bg-red-500 text-white" title="Run failed" time={event.created_at}>
          <p className="text-xs text-red-700">{str(d.error)}</p>
        </Row>
      );
    case "warning":
      return <Row icon={<AlertTriangle className={i} />} tone="bg-amber-100 text-amber-700" title={str(d.message)} agent={event.agent} time={event.created_at} />;
    default:
      return <Row icon={<CircleDot className={i} />} tone="bg-slate-100 text-slate-500" title={event.type} time={event.created_at} />;
  }
}

export function Timeline({ events, showLlm = true }: { events: RunEvent[]; showLlm?: boolean }) {
  return (
    <ol className="relative space-y-4 before:absolute before:bottom-2 before:left-3 before:top-2 before:w-px before:bg-slate-200">
      {events.map((event) => (
        <EventRow key={event.id} event={event} showLlm={showLlm} />
      ))}
    </ol>
  );
}
