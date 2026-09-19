import clsx from "clsx";
import { Inbox } from "lucide-react";
import { useState } from "react";

import { ApprovalCard } from "../components/ApprovalCard";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { usePolling } from "../lib/hooks";

export function ApprovalsPage() {
  const [tab, setTab] = useState<"pending" | "history">("pending");
  const approvals = usePolling(() => api.listApprovals(tab === "pending" ? { status: "pending" } : {}), 3000, [tab]);
  const items = (approvals.data ?? []).filter((a) => (tab === "pending" ? a.status === "pending" : a.status !== "pending"));

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Approvals inbox"
        subtitle="Runs pause here when the risk policy requires a human: large refunds, outbound email, explicit escalations and low-confidence answers."
        actions={
          <div className="flex rounded-lg bg-slate-100 p-1 text-sm">
            {(["pending", "history"] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={clsx("rounded-md px-3 py-1 font-medium capitalize", tab === t ? "bg-white text-slate-900 shadow-sm" : "text-slate-500")}
              >
                {t}
              </button>
            ))}
          </div>
        }
      />
      <div className="scrollbar-thin flex-1 overflow-y-auto px-8 py-6">
        <div className="mx-auto max-w-3xl space-y-4">
          {approvals.loading && !approvals.data && <Spinner className="mx-auto h-6 w-6" />}
          {approvals.error && <p className="text-sm text-red-600">{approvals.error}</p>}
          {approvals.data && items.length === 0 && (
            <EmptyState icon={<Inbox className="h-5 w-5" />} title={tab === "pending" ? "Inbox zero" : "No decisions yet"}>
              {tab === "pending" ? "Nothing is waiting for a human right now." : "Approved and rejected actions will appear here."}
            </EmptyState>
          )}
          {items.map((approval) => (
            <ApprovalCard key={approval.id} approval={approval} onDecided={() => void approvals.reload()} />
          ))}
        </div>
      </div>
    </div>
  );
}
