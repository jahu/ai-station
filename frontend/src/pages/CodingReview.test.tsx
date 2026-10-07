import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import type { Run } from "../api";
import CodingReview from "./CodingReview";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("requires review acknowledgement and opens the queued commit", async () => {
  const fetch = vi.fn(async () => ({
    ok: true,
    json: async () => ({ id: "commit" }),
  }));
  vi.stubGlobal("fetch", fetch);
  const run = {
    id: "coding",
    status: "succeeded",
    summary: "Fix selected files",
    metadata: {
      coding_review: {
        branch: "ai/test",
        files: [
          { path: "file.py", diff: "+print(42)", insertions: 1, deletions: 0 },
        ],
      },
    },
  } as unknown as Run;
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <Routes>
          <Route path="/" element={<CodingReview run={run} />} />
          <Route path="/runs/:id" element={<h1>Commit Run</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const button = screen.getByRole("button", {
    name: "Commit reviewed changes",
  });
  expect(button.hasAttribute("disabled")).toBe(true);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(button);
  await screen.findByRole("heading", { name: "Commit Run" });
  expect(fetch).toHaveBeenCalledWith(
    "/api/coding/runs/coding/commit",
    expect.objectContaining({
      body: JSON.stringify({ message: "Fix selected files", reviewed: true }),
    }),
  );
});

it("offers a local repair only after confirmed failing validation", async () => {
  const fetch = vi.fn(async (_url: string, options?: RequestInit) => ({
    ok: true,
    json: async () =>
      options
        ? { id: "repair" }
        : {
            id: "validation",
            status: "failed",
            error_type: "ValidationFailed",
          },
  }));
  vi.stubGlobal("fetch", fetch);
  const run = {
    id: "coding",
    executor_type: "local_proposal",
    status: "succeeded",
    metadata: {
      execution_location: "local",
      validation_run_id: "validation",
      coding_review: { branch: "ai/task", files: [] },
    },
  } as unknown as Run;
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <Routes>
          <Route path="/" element={<CodingReview run={run} />} />
          <Route path="/runs/repair" element={<h1>Repair Run</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const repairButton = await screen.findByRole("button", {
    name: "Repair with Local AI",
  });
  expect(
    screen.queryByRole("button", { name: "Commit reviewed changes" }),
  ).toBeNull();
  fireEvent.click(repairButton);
  await screen.findByRole("heading", { name: "Repair Run" });
  expect(fetch).toHaveBeenCalledWith(
    "/api/coding/runs/coding/repair",
    expect.objectContaining({ method: "POST" }),
  );
});

it("links to an existing repair and prevents committing a superseded proposal", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({ status: "failed", error_type: "ValidationFailed" }),
    })),
  );
  const run = {
    id: "coding",
    executor_type: "local_proposal",
    status: "succeeded",
    metadata: {
      execution_location: "local",
      validation_run_id: "validation",
      repair_run_id: "repair",
      coding_review: {
        branch: "ai/task",
        files: [
          { path: "new.py", diff: "+print(42)", insertions: 1, deletions: 0 },
        ],
      },
    },
  } as unknown as Run;
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <CodingReview run={run} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByText("Validation: failed →");
  expect(
    screen.getByRole("link", { name: "Open repair →" }).getAttribute("href"),
  ).toBe("/runs/repair");
  expect(
    screen.queryByRole("button", { name: "Commit reviewed changes" }),
  ).toBeNull();
  expect(
    screen.queryByRole("button", { name: "Repair with Local AI" }),
  ).toBeNull();
});
