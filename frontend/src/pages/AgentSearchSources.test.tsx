import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  AgentSearchSources,
  isSearchPageResult,
  type SearchPageResult,
} from "./AgentSearchSources";
import { AgentLatestReport } from "./AgentLatestReport";
import type { Run } from "../api";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const result: SearchPageResult = {
  query: "public release notes",
  fetched_at: "2026-10-23T08:00:00Z",
  partial: false,
  search_artifact_id: "search-source",
  errors: [],
  urls: ["https://example.com/releases"],
  pages: [
    {
      url: "https://example.com/releases",
      status: 200,
      text: "<script>untrusted</script>Actual text",
      untrusted: true,
    },
  ],
};
it("separates actually read pages from search snippets and exposes source provenance without loading them", () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  render(
    <MemoryRouter>
      <AgentSearchSources result={result} />
    </MemoryRouter>,
  );
  expect(
    screen.getByRole("region", { name: "Search source reading" }),
  ).toBeTruthy();
  expect(screen.getByText(/1 of 1 sources provided text/)).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "Search snapshot" }).getAttribute("href"),
  ).toBe("/library/search-source");
  expect(
    screen.getByRole("region", { name: "Read search sources" }),
  ).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "Page https://example.com/releases" }),
  ).toBeTruthy();
  expect(document.querySelector("script")).toBeNull();
  expect(fetch).not.toHaveBeenCalled();
});
it("makes an unreadable source visible without claiming its page text was read", () => {
  render(
    <MemoryRouter>
      <AgentSearchSources
        result={{
          ...result,
          partial: true,
          pages: [],
          errors: [
            {
              url: "https://example.com/releases",
              error: "Public source unavailable",
            },
          ],
        }}
      />
    </MemoryRouter>,
  );
  expect(screen.getByRole("status").textContent).toContain("could not be read");
  expect(screen.getByText(/0 of 1 sources provided text/)).toBeTruthy();
  expect(screen.getByText(/Public source unavailable/)).toBeTruthy();
  expect(screen.getByText("No pages were fetched.")).toBeTruthy();
});
it("projects the new page observation into the agent's existing latest report", async () => {
  const fetch = vi.fn(async (_url: string) => ({
    ok: true,
    json: async () => [],
  }));
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <AgentLatestReport
          runs={[
            {
              id: "report",
              executor_type: "agent",
              status: "succeeded",
              metadata: { search_pages: result },
            } as unknown as Run,
          ]}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(
    await screen.findByRole("region", { name: "Read search sources" }),
  ).toBeTruthy();
  expect(
    fetch.mock.calls.every((args) =>
      String(args[0]).includes("/artifacts?run_id=report"),
    ),
  ).toBe(true);
});
it("rejects malformed saved source observations instead of crashing the result view", () => {
  expect(isSearchPageResult(result)).toBe(true);
  expect(isSearchPageResult({ ...result, pages: [null] })).toBe(false);
  expect(
    isSearchPageResult({
      ...result,
      pages: [{ url: "https://example.com", error: {} }],
    }),
  ).toBe(false);
  expect(
    isSearchPageResult({ ...result, errors: [{ url: "https://example.com" }] }),
  ).toBe(false);
});
