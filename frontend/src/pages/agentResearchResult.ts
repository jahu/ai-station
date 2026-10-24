import type { WebSources } from "./ChatWebSearch";
import type { FetchResult } from "./AgentHttpFetch";

export function isWebSources(value: unknown): value is WebSources {
  if (!value || typeof value !== "object") return false;
  const result = value as Record<string, unknown>;
  return (
    typeof result.query === "string" &&
    typeof result.searched_at === "string" &&
    Array.isArray(result.sources)
  );
}

export function isFetchResult(value: unknown): value is FetchResult {
  if (!value || typeof value !== "object") return false;
  const result = value as Record<string, unknown>;
  return (
    Array.isArray(result.urls) &&
    typeof result.fetched_at === "string" &&
    Array.isArray(result.pages)
  );
}

type Entry = {
  id: string;
  content: string;
  updated_at: string;
  source_run_id?: string | null;
};
export function memoryObservation(
  value: unknown,
): value is { scope: "agent" | "project"; scope_id: string; entries: Entry[] } {
  if (!value || typeof value !== "object") return false;
  const data = value as Record<string, unknown>;
  return (
    ["agent", "project"].includes(String(data.scope)) &&
    typeof data.scope_id === "string" &&
    Array.isArray(data.entries) &&
    data.entries.length <= 20 &&
    data.entries.every(
      (entry) =>
        entry &&
        typeof entry.id === "string" &&
        typeof entry.content === "string" &&
        typeof entry.updated_at === "string",
    )
  );
}
