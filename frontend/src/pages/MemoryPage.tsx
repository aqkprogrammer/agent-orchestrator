import { Brain, Plus, Search, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { PageHeader } from "../components/PageHeader";
import { Badge, Button, Card, EmptyState, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { timeAgo } from "../lib/format";
import { usePolling } from "../lib/hooks";
import type { Memory } from "../lib/types";
import { useUser } from "../lib/user";

const KIND_TONE = { profile: "indigo", preference: "amber", fact: "slate" } as const;

export function MemoryPage() {
  const { userId } = useUser();
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [content, setContent] = useState("");
  const [kind, setKind] = useState<Memory["kind"]>("fact");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(query), 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  const memories = usePolling(() => api.listMemories(userId, debounced || undefined), 0, [userId, debounced]);

  const add = async () => {
    if (content.trim().length < 3) return;
    setSaving(true);
    setError(null);
    try {
      await api.addMemory(userId, content.trim(), kind);
      setContent("");
      await memories.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id: string) => {
    await api.deleteMemory(id, userId);
    await memories.reload();
  };

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Long-term memory"
        subtitle={
          <>
            Facts extracted from conversations for <span className="font-mono text-slate-700">{userId}</span>. Stored in
            Postgres, embedded into ChromaDB and recalled semantically at the start of every run.
          </>
        }
      />
      <div className="scrollbar-thin flex-1 overflow-y-auto px-8 py-6">
        <div className="mx-auto max-w-3xl space-y-5">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Semantic search, e.g. 'what is my name'"
              className="w-full rounded-xl border border-slate-300 bg-white py-2.5 pl-9 pr-3 text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-100"
            />
          </div>

          <Card className="p-3">
            <form
              className="flex flex-wrap gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                void add();
              }}
            >
              <input
                value={content}
                onChange={(e) => setContent(e.target.value)}
                placeholder="Add a memory manually..."
                maxLength={500}
                className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
              />
              <select
                value={kind}
                onChange={(e) => setKind(e.target.value as Memory["kind"])}
                className="rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm"
              >
                <option value="fact">fact</option>
                <option value="preference">preference</option>
                <option value="profile">profile</option>
              </select>
              <Button type="submit" loading={saving} disabled={content.trim().length < 3}>
                <Plus className="h-4 w-4" /> Add
              </Button>
            </form>
            {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
          </Card>

          {memories.loading && !memories.data && <Spinner className="mx-auto h-6 w-6" />}
          {memories.data?.length === 0 && (
            <EmptyState icon={<Brain className="h-5 w-5" />} title={debounced ? "No matching memories" : "No memories yet"}>
              Tell the agents something about yourself, e.g. "My name is Dana and I prefer concise answers."
            </EmptyState>
          )}
          <ul className="space-y-2">
            {memories.data?.map((m) => (
              <li key={m.id}>
                <Card className="group flex items-start gap-3 px-4 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-slate-800">{m.content}</p>
                    <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
                      <Badge tone={KIND_TONE[m.kind]}>{m.kind}</Badge>
                      {m.score !== null && <Badge tone="green">similarity {m.score.toFixed(2)}</Badge>}
                      <span>{timeAgo(m.created_at)}</span>
                      {m.source_run_id && (
                        <Link to={`/runs/${m.source_run_id}`} className="text-indigo-600 hover:underline">
                          source run
                        </Link>
                      )}
                    </div>
                  </div>
                  <Button variant="ghost" size="sm" aria-label="Delete memory" onClick={() => void remove(m.id)} className="opacity-60 group-hover:opacity-100">
                    <Trash2 className="h-4 w-4 text-red-500" />
                  </Button>
                </Card>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
