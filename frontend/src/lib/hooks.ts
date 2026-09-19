import { useCallback, useEffect, useRef, useState } from "react";

import { streamUrl } from "./api";
import type { RunEvent } from "./types";

const TERMINAL = new Set(["run_completed", "run_failed"]);

/** Subscribe to a run's Server-Sent Events. Replays history, then streams live. */
export function useRunStream(runId: string | null, onEvent?: (event: RunEvent) => void) {
  const [state, setState] = useState<{ runId: string | null; events: RunEvent[]; connected: boolean }>({
    runId: null,
    events: [],
    connected: false,
  });
  const callback = useRef(onEvent);

  useEffect(() => {
    callback.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    if (!runId) return;
    const source = new EventSource(streamUrl(runId));
    const seen = new Set<number>();
    const update = (fn: (events: RunEvent[]) => RunEvent[], connected: boolean) =>
      setState((prev) => ({
        runId,
        events: fn(prev.runId === runId ? prev.events : []),
        connected,
      }));
    source.onopen = () => update((events) => events, true);
    source.onerror = () => update((events) => events, false);
    source.addEventListener("run_event", (message) => {
      const event = JSON.parse((message as MessageEvent<string>).data) as RunEvent;
      if (seen.has(event.id)) return;
      seen.add(event.id);
      const terminal = TERMINAL.has(event.type);
      if (terminal) source.close();
      update((events) => [...events, event], !terminal);
      callback.current?.(event);
    });
    return () => source.close();
  }, [runId]);

  const current = state.runId === runId;
  return { events: current ? state.events : [], connected: current && state.connected };
}

/** Load data (and optionally re-poll). Data is keyed by `deps`, so stale results are hidden. */
export function usePolling<T>(loader: () => Promise<T>, intervalMs: number, deps: unknown[]) {
  const key = JSON.stringify(deps);
  const [state, setState] = useState<{ key: string | null; data: T | null; error: string | null }>({
    key: null,
    data: null,
    error: null,
  });
  const loaderRef = useRef(loader);
  const keyRef = useRef(key);

  useEffect(() => {
    loaderRef.current = loader;
    keyRef.current = key;
  });

  const reload = useCallback(async () => {
    const requestKey = keyRef.current;
    try {
      const data = await loaderRef.current();
      if (requestKey === keyRef.current) setState({ key: requestKey, data, error: null });
    } catch (err) {
      const error = err instanceof Error ? err.message : String(err);
      if (requestKey === keyRef.current) setState((prev) => ({ ...prev, key: requestKey, error }));
    }
  }, []);

  useEffect(() => {
    void reload();
    if (intervalMs <= 0) return;
    const timer = window.setInterval(() => void reload(), intervalMs);
    return () => window.clearInterval(timer);
  }, [reload, intervalMs, key]);

  const current = state.key === key;
  return {
    data: current ? state.data : null,
    error: current ? state.error : null,
    loading: !current,
    reload,
  };
}
