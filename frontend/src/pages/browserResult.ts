export type BrowserResult = {
  captured_at: number;
  pages: {
    url: string;
    title: string;
    text: string;
    screenshot_artifact_id: string;
    truncated: boolean;
    blocked_resource_count: number;
  }[];
};

export function isBrowserResult(value: unknown): value is BrowserResult {
  if (!value || typeof value !== "object") return false;
  const result = value as BrowserResult;
  return (
    typeof result.captured_at === "number" &&
    Number.isFinite(result.captured_at) &&
    Array.isArray(result.pages) &&
    result.pages.every(
      (page) =>
        page &&
        typeof page.url === "string" &&
        isPublicLink(page.url) &&
        typeof page.title === "string" &&
        typeof page.text === "string" &&
        typeof page.screenshot_artifact_id === "string" &&
        typeof page.truncated === "boolean" &&
        Number.isInteger(page.blocked_resource_count) &&
        page.blocked_resource_count >= 0,
    )
  );
}

function isPublicLink(value: string): boolean {
  try {
    const url = new URL(value);
    return (
      ["http:", "https:"].includes(url.protocol) &&
      !!url.hostname &&
      !url.username &&
      !url.password
    );
  } catch {
    return false;
  }
}
