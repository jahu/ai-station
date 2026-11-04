import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import type { Artifact } from "../api";
import AgentReport from "./AgentReport";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("renders a complete Markdown report with links but never fetches remote images", async () => {
  const fetch = vi.fn(async () => ({
    ok: true,
    text: async () =>
      "## Findings\n\n[Source](https://example.org/paper)\n\n![Tracking image](https://example.org/tracker.png)\n\nFinal paragraph beyond the summary.",
  }));
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <AgentReport
        artifacts={[
          {
            id: "report",
            type: "markdown",
            mime_type: "text/markdown",
            original_filename: "agent-report.md",
            size_bytes: 100,
            created_at: "2026-09-30T12:00:00Z",
            run_id: "run",
            parent_artifact_ids: [],
            metadata: { partial: true },
          } as Artifact,
        ]}
      />
    </QueryClientProvider>,
  );
  await screen.findByRole("heading", { name: "Findings" });
  expect(screen.getByRole("heading", { name: "Partial report" })).toBeTruthy();
  expect(screen.getByText("Final paragraph beyond the summary.")).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "Source" }).getAttribute("href"),
  ).toBe("https://example.org/paper");
  expect(screen.queryByRole("img")).toBeNull();
  expect(fetch).toHaveBeenCalledExactlyOnceWith(
    "/api/artifacts/report/file",
    undefined,
  );
});

it("links an explicitly retained excerpt to inspectable memory", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, text: async () => "Full report" })),
  );
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <AgentReport
          memoryId="saved-observation"
          excerpted
          artifacts={[
            { id: "report", type: "markdown", metadata: {} } as Artifact,
          ]}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByText("Full report");
  expect(
    screen
      .getByRole("link", { name: "View saved agent memory →" })
      .getAttribute("href"),
  ).toBe("/memory/saved-observation");
  expect(screen.getByText(/Memory contains an excerpt/)).toBeTruthy();
});
