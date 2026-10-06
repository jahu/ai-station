import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type RunEvent } from "../api";

export function useRunEvents(id: string | undefined) {
  const cache = useQueryClient();
  const query = useQuery({
    queryKey: ["events", id],
    queryFn: async () => {
      const rows = await api<RunEvent[]>(`/runs/${id}/events`);
      const latest = rows.at(-1)?.sequence ?? 0;
      const streamed = cache.getQueryData<RunEvent[]>(["events", id]) ?? [];
      return [...rows, ...streamed.filter((event) => event.sequence > latest)];
    },
    enabled: !!id,
  });
  useEffect(() => {
    if (!id || !query.isSuccess) return;
    const key = ["events", id];
    const cursor = cache.getQueryData<RunEvent[]>(key)?.at(-1)?.sequence ?? 0;
    const source = new EventSource(`/api/runs/${id}/stream?after=${cursor}`);
    let pending: RunEvent[] = [];
    let timer: ReturnType<typeof setTimeout> | undefined;
    function flush() {
      clearTimeout(timer);
      timer = undefined;
      const batch = pending;
      pending = [];
      if (!batch.length) return;
      cache.setQueryData<RunEvent[]>(key, (current) => {
        const seen = new Set(current?.map((e) => e.sequence));
        const added = batch.filter((e) => {
          if (seen.has(e.sequence)) return false;
          seen.add(e.sequence);
          return true;
        });
        return [...(current ?? []), ...added].sort(
          (a, b) => a.sequence - b.sequence,
        );
      });
      if (
        batch.some(
          (e) =>
            e.event_type.startsWith("run.") ||
            e.event_type.startsWith("executor."),
        )
      ) {
        void cache.invalidateQueries({ queryKey: ["run", id] });
      }
      if (batch.some((e) => e.event_type === "artifact.created"))
        void cache.invalidateQueries({ queryKey: ["run-artifacts", id] });
    }
    source.onmessage = (event) => {
      try {
        pending.push(JSON.parse(event.data) as RunEvent);
      } catch {
        return;
      }
      timer ??= setTimeout(flush, 250);
    };
    source.addEventListener("end", () => {
      flush();
      source.close();
      void cache.invalidateQueries({ queryKey: ["run", id] });
      void cache.invalidateQueries({ queryKey: ["run-artifacts", id] });
    });
    return () => {
      flush();
      source.close();
    };
  }, [id, query.isSuccess, cache]);
  return query;
}
