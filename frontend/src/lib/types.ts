export type RunStatus = "queued" | "running" | "awaiting_approval" | "completed" | "failed";

export interface Run {
  id: string;
  thread_id: string;
  user_id: string;
  task: string;
  status: RunStatus;
  final_answer: string | null;
  confidence: number | null;
  error: string | null;
  llm_provider: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  llm_calls: number;
  tool_calls: number;
  latency_ms: number;
  created_at: string | null;
  updated_at: string | null;
  completed_at: string | null;
}

export interface RunDetail extends Run {
  pending_approval: Approval | null;
}

export interface RunEvent {
  id: number;
  run_id: string;
  type: string;
  agent: string | null;
  data: Record<string, unknown>;
  created_at: string | null;
}

export interface Thread {
  id: string;
  user_id: string;
  title: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface ConversationTurn {
  role: "user" | "assistant";
  content: string;
  run_id?: string;
}

export interface ThreadDetail {
  thread: Thread;
  runs: Run[];
  conversation: ConversationTurn[];
  checkpoint_id: string | null;
}

export type ApprovalKind = "tool" | "escalation" | "final_review";
export type ApprovalStatus = "pending" | "approved" | "rejected" | "edited";

export interface Approval {
  id: string;
  run_id: string;
  thread_id: string;
  user_id: string;
  kind: ApprovalKind;
  agent: string | null;
  tool_name: string | null;
  args: Record<string, unknown>;
  reason: string;
  risk_level: "low" | "medium" | "high";
  payload: Record<string, unknown>;
  status: ApprovalStatus;
  decision: Record<string, unknown> | null;
  reviewer: string | null;
  created_at: string | null;
  decided_at: string | null;
}

export interface DecisionInput {
  decision: "approve" | "reject" | "edit";
  args?: Record<string, unknown>;
  response?: string;
  comment?: string;
  reviewer?: string;
}

export interface Memory {
  id: string;
  user_id: string;
  content: string;
  kind: "profile" | "preference" | "fact";
  source_run_id: string | null;
  created_at: string | null;
  score: number | null;
}

export interface AuditEntry {
  id: number;
  run_id: string | null;
  user_id: string;
  agent: string | null;
  action: string;
  args: Record<string, unknown>;
  result: Record<string, unknown> | null;
  status: string;
  latency_ms: number;
  created_at: string | null;
}

export interface AppConfig {
  version: string;
  llm: { provider: string; model: string };
  embedding: { provider: string; dim: number };
  infrastructure: Record<string, string>;
  limits: Record<string, number>;
  policy: {
    refund_approval_threshold: number;
    email_requires_approval: boolean;
    confidence_threshold: number;
  };
  agents: { name: string; title: string; description: string; tools: string[] }[];
  tools: { name: string; description: string; risk: string; sensitive: boolean }[];
}
