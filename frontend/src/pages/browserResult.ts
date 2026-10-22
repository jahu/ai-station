export type BrowserResult = {
  captured_at: number;
  reused_from_message_id?: string;
  visual_analysis?: {
    run_id: string;
    artifact_id: string;
    model: string;
    description: string;
    truncated: boolean;
    location: "local";
    screenshot_id: string;
  };
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
    (!result.visual_analysis ||
      (result.visual_analysis.location === "local" &&
        [
          result.visual_analysis.model,
          result.visual_analysis.run_id,
          result.visual_analysis.artifact_id,
          result.visual_analysis.screenshot_id,
        ].every((value) => typeof value === "string" && value.length > 0) &&
        typeof result.visual_analysis.description === "string" &&
        typeof result.visual_analysis.truncated === "boolean")) &&
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
