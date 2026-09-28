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
