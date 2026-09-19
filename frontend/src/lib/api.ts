import type {
  AppConfig,
  Approval,
  AuditEntry,
  DecisionInput,
  Memory,
  Run,
  RunDetail,
  RunEvent,
  Thread,
  ThreadDetail,
} from "./types";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    let message = response.statusText;
    try {
      const body = await response.json();
      message =
        typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const qs = (params: Record<string, string | number | undefined | null>) => {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
};

export const api = {
  config: () => request<AppConfig>("/api/config"),
  health: () => request<{ status: string }>("/health/ready"),

  createRun: (task: string, userId: string, threadId?: string | null) =>
    request<Run>("/api/runs", {
      method: "POST",
      body: JSON.stringify({ task, user_id: userId, thread_id: threadId ?? undefined }),
    }),
  listRuns: (params: { user_id?: string; status?: string; limit?: number }) =>
    request<Run[]>(`/api/runs${qs(params)}`),
  getRun: (id: string) => request<RunDetail>(`/api/runs/${id}`),
  runEvents: (id: string) => request<RunEvent[]>(`/api/runs/${id}/events`),
  runAudit: (id: string) => request<AuditEntry[]>(`/api/runs/${id}/audit`),

  listThreads: (userId: string) => request<Thread[]>(`/api/threads${qs({ user_id: userId })}`),
  getThread: (id: string) => request<ThreadDetail>(`/api/threads/${id}`),

  listApprovals: (params: { status?: string; user_id?: string }) =>
    request<Approval[]>(`/api/approvals${qs(params)}`),
  decide: (id: string, body: DecisionInput) =>
    request<Approval>(`/api/approvals/${id}/decision`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  listMemories: (userId: string, q?: string) =>
    request<Memory[]>(`/api/memories${qs({ user_id: userId, q })}`),
  addMemory: (userId: string, content: string, kind: Memory["kind"]) =>
    request<Memory>("/api/memories", {
      method: "POST",
      body: JSON.stringify({ user_id: userId, content, kind }),
    }),
  deleteMemory: (id: string, userId: string) =>
    request<void>(`/api/memories/${id}${qs({ user_id: userId })}`, { method: "DELETE" }),
};

export const streamUrl = (runId: string) => `/api/runs/${runId}/stream`;
