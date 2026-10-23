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
