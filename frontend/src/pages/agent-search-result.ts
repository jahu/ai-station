import type { FetchResult } from "./AgentHttpFetch";

export type SearchPageResult = FetchResult & {
  query: string;
  partial: boolean;
  search_artifact_id: string;
  errors: { url: string; error: string }[];
};

export function isSearchPageResult(value: unknown): value is SearchPageResult {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return (
    typeof item.query === "string" &&
    typeof item.partial === "boolean" &&
    typeof item.search_artifact_id === "string" &&
    typeof item.fetched_at === "string" &&
    Array.isArray(item.urls) &&
    item.urls.every((url) => typeof url === "string") &&
    Array.isArray(item.pages) &&
    item.pages.every(
      (page) =>
        page &&
        typeof page === "object" &&
        typeof page.url === "string" &&
        (page.text === undefined || typeof page.text === "string") &&
        (page.error === undefined || typeof page.error === "string") &&
        (page.skipped === undefined || typeof page.skipped === "string"),
    ) &&
    Array.isArray(item.errors) &&
    item.errors.every(
      (error) =>
        error &&
        typeof error === "object" &&
        typeof error.url === "string" &&
        typeof error.error === "string",
    )
  );
}
