import { Check, ExternalLink, Pencil, ShieldAlert, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../lib/api";
import { timeAgo, titleCase } from "../lib/format";
import type { Approval, DecisionInput } from "../lib/types";
import { AgentBadge, Badge, Button, Card, JsonBlock } from "./ui";

const RISK_TONE = { low: "green", medium: "amber", high: "red" } as const;

export function ApprovalCard({ approval, onDecided, compact = false }: {
  approval: Approval;
  onDecided?: (approval: Approval) => void;
  compact?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [argsText, setArgsText] = useState(() => JSON.stringify(approval.args, null, 2));
  const [response, setResponse] = useState(
    approval.kind === "final_review" ? String(approval.args.answer ?? "") : "",
  );
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pending = approval.status === "pending";

  const submit = async (decision: DecisionInput["decision"]) => {
    setError(null);
    const body: DecisionInput = { decision, comment: comment || undefined, reviewer: "console-reviewer" };
    if (decision === "edit") {
      if (approval.kind === "tool") {
        try {
          body.args = JSON.parse(argsText) as Record<string, unknown>;
        } catch {
          setError("Arguments must be valid JSON.");
          return;
        }
      } else {
        body.response = response;
      }
    }
    if (decision === "approve" && approval.kind === "escalation" && response) body.response = response;
    setBusy(decision);
    try {
      onDecided?.(await api.decide(approval.id, body));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  const title =
    approval.kind === "tool"
      ? `Run ${approval.tool_name}`
      : approval.kind === "escalation"
        ? "Agent escalated to a human"
        : "Review low-confidence answer";

  return (
    <Card className={pending ? "border-amber-300 ring-1 ring-amber-200" : ""}>
      <div className="flex flex-wrap items-start gap-3 p-4">
        <div className="rounded-lg bg-amber-100 p-2 text-amber-700">
          <ShieldAlert className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold text-slate-900">{title}</h3>
            <AgentBadge agent={approval.agent} />
            <Badge tone={RISK_TONE[approval.risk_level] ?? "slate"}>{approval.risk_level} risk</Badge>
            {!pending && <Badge tone={approval.status === "rejected" ? "red" : "green"}>{approval.status}</Badge>}
          </div>
          <p className="mt-1 text-sm text-slate-600">{approval.reason}</p>
          <p className="mt-1 text-xs text-slate-400">
            {timeAgo(approval.created_at)} · user <span className="font-mono">{approval.user_id}</span>
            {!compact && (
              <>
                {" · "}
                <Link to={`/runs/${approval.run_id}`} className="inline-flex items-center gap-0.5 text-indigo-600 hover:underline">
                  view run <ExternalLink className="h-3 w-3" />
                </Link>
              </>
            )}
          </p>
        </div>
      </div>

      <div className="space-y-3 border-t border-slate-100 px-4 py-3">
        {approval.kind === "tool" &&
          (editing && pending ? (
            <textarea
              value={argsText}
              onChange={(e) => setArgsText(e.target.value)}
              rows={Math.min(12, argsText.split("\n").length + 1)}
              spellCheck={false}
              className="w-full rounded-lg border border-slate-300 bg-slate-900 p-3 font-mono text-xs text-slate-100 focus:border-indigo-500 focus:outline-none"
            />
          ) : (
            <JsonBlock value={approval.args} />
          ))}
        {approval.kind === "escalation" && (
          <div className="space-y-2">
            <p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-700 ring-1 ring-inset ring-slate-200">
              {String(approval.args.question ?? "")}
            </p>
            {pending && (
              <textarea
                value={response}
                onChange={(e) => setResponse(e.target.value)}
                rows={2}
                placeholder="Guidance for the agent (e.g. 'Offer a 20% voucher and apologise')"
                className="w-full rounded-lg border border-slate-300 p-2.5 text-sm focus:border-indigo-500 focus:outline-none"
              />
            )}
          </div>
        )}
        {approval.kind === "final_review" &&
          (pending ? (
            <textarea
              value={response}
              onChange={(e) => setResponse(e.target.value)}
              rows={6}
              className="w-full rounded-lg border border-slate-300 p-2.5 text-sm focus:border-indigo-500 focus:outline-none"
            />
          ) : (
            <p className="whitespace-pre-wrap text-sm text-slate-600">{String(approval.args.answer ?? "")}</p>
          ))}
        {!pending && approval.decision && (
          <p className="text-xs text-slate-500">
            {titleCase(String(approval.decision.decision))} by {approval.reviewer}
            {approval.decision.comment ? ` - "${String(approval.decision.comment)}"` : ""}
          </p>
        )}
      </div>

      {pending && (
        <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 bg-slate-50/60 px-4 py-3">
          <input
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Optional comment"
            className="min-w-0 flex-1 rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm focus:border-indigo-500 focus:outline-none"
          />
          {approval.kind === "tool" && !editing && (
            <Button variant="secondary" size="sm" onClick={() => setEditing(true)}>
              <Pencil className="h-3.5 w-3.5" /> Edit
            </Button>
          )}
          <Button variant="danger" size="sm" loading={busy === "reject"} onClick={() => void submit("reject")}>
            <X className="h-3.5 w-3.5" /> Reject
          </Button>
          {(editing || approval.kind === "final_review") && (
            <Button variant="primary" size="sm" loading={busy === "edit"} onClick={() => void submit("edit")}>
              <Pencil className="h-3.5 w-3.5" /> {approval.kind === "final_review" ? "Send edited" : "Approve edited"}
            </Button>
          )}
          <Button variant="success" size="sm" loading={busy === "approve"} onClick={() => void submit("approve")}>
            <Check className="h-3.5 w-3.5" /> Approve
          </Button>
          {error && <p className="w-full text-xs text-red-600">{error}</p>}
        </div>
      )}
    </Card>
  );
}
