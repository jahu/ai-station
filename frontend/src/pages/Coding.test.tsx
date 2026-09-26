import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import Coding from "./Coding";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("requires explicit external consent and queues a fresh-worktree task with selected paths", async () => {
  const fetch = vi.fn(async (_path: string, options?: RequestInit) => ({
    ok: true,
    json: async () =>
      options?.method === "POST"
        ? { id: "prepare" }
        : [
            {
              id: "project",
              name: "Example",
              updated_at: "version",
              integration_branch: "develop",
            },
          ],
  }));
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={["/coding"]}>
        <Routes>
          <Route path="/coding" element={<Coding />} />
          <Route path="/runs/prepare" element={<h1>Prepare Run</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.change(await screen.findByLabelText("Project"), {
    target: { value: "project" },
  });
  fireEvent.change(screen.getByLabelText("Task"), {
    target: { value: "Fix selected source" },
  });
  const button = screen.getByRole("button", {
    name: "Create worktree and start Cursor",
  });
  expect((button as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(button);
  await screen.findByRole("heading", { name: "Prepare Run" });
  expect(fetch).toHaveBeenCalledWith(
    "/api/coding/cursor",
    expect.objectContaining({
      body: JSON.stringify({
        project_id: "project",
        expected_updated_at: "version",
        prompt: "Fix selected source",
        files: ["README.md"],
        model: "",
        external_ai: true,
      }),
    }),
  );
});
