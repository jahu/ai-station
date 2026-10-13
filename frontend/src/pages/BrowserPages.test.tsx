import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BrowserPages } from "./BrowserPages";
import { isBrowserResult } from "./browserResult";

describe("rendered page evidence", () => {
  it("shows the saved screenshot, captured text and partial-page warning", () => {
    render(
      <BrowserPages
        result={{
          captured_at: 1000,
          pages: [
            {
              url: "https://example.com/page",
              title: "Company page",
              text: "<script>untrusted text</script>",
              screenshot_artifact_id: "saved-image",
              truncated: true,
              blocked_resource_count: 2,
            },
          ],
        }}
      />,
    );
    expect(
      screen
        .getByRole("img", { name: "Screenshot of Company page" })
        .getAttribute("src"),
    ).toBe("/api/artifacts/saved-image/file");
    expect(
      screen
        .getByRole("link", { name: "Open screenshot of Company page" })
        .getAttribute("href"),
    ).toBe("/api/artifacts/saved-image/file");
    expect(screen.getByText(/2 resources could not/)).toBeTruthy();
    expect(screen.getByText("<script>untrusted text</script>")).toBeTruthy();
    expect(document.querySelector("script")).toBeNull();
    expect(screen.getByText(/Read captured text \(excerpt\)/)).toBeTruthy();
  });
  it("rejects malformed evidence and non-HTTP links", () => {
    expect(
      isBrowserResult({
        captured_at: 1000,
        pages: [{ url: "javascript:alert(1)" }],
      }),
    ).toBe(false);
    expect(isBrowserResult({ captured_at: 1000, pages: [] })).toBe(true);
    expect(
      isBrowserResult({
        captured_at: 1000,
        pages: [
          {
            url: "https://",
            title: "",
            text: "",
            screenshot_artifact_id: "id",
            truncated: false,
            blocked_resource_count: 0,
          },
        ],
      }),
    ).toBe(false);
  });
});
