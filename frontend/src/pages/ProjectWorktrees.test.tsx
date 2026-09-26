import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ProjectWorktrees from "./ProjectWorktrees";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("queues an explicit versioned preparation Run and opens its inspector", async () => {
  const fetch = vi.fn(async (_path: string, options?: RequestInit) => ({
    ok: true,
    json: async () => (options?.method === "POST" ? { id: "prepared" } : []),
  }));
  vi.stubGlobal("fetch", fetch);
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={cache}>
      <MemoryRouter initialEntries={["/projects/one"]}>
        <Routes>
          <Route
            path="/projects/one"
            element={
              <ProjectWorktrees
                project={{
                  id: "one",
                  updated_at: "version",
                  integration_branch: "develop",
                }}
              />
            }
          />
          <Route path="/runs/prepared" element={<h1>Preparation Run</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByText("No worktrees prepared");
  expect(
    fetch.mock.calls.filter(([, options]) => options?.method === "POST"),
  ).toHaveLength(0);
  fireEvent.click(
    screen.getByRole("button", { name: "Prepare isolated worktree" }),
  );
  await screen.findByRole("heading", { name: "Preparation Run" });
  expect(fetch).toHaveBeenCalledWith(
    "/api/projects/one/worktrees",
    expect.objectContaining({
      method: "POST",
      body: '{"expected_updated_at":"version"}',
    }),
  );
});

it("queues saved validation for a ready owned worktree without sending commands", async () => {
  const fetch = vi.fn(async (_path: string, options?: RequestInit) => ({
    ok: true,
    json: async () =>
      options?.method === "POST"
        ? { id: "validation" }
        : [
            {
              id: "worktree",
              run_id: "preparation",
              run_status: "succeeded",
              owned: true,
              branch: "ai/task",
              relative_path: "worktrees/project/task",
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
      <MemoryRouter initialEntries={["/projects/one"]}>
        <Routes>
          <Route
            path="/projects/one"
            element={
              <ProjectWorktrees
                project={{
                  id: "one",
                  updated_at: "version",
                  integration_branch: "develop",
                }}
              />
            }
          />
          <Route path="/runs/validation" element={<h1>Validation Run</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Run saved validation" }),
  );
  await screen.findByRole("heading", { name: "Validation Run" });
  expect(fetch).toHaveBeenCalledWith(
    "/api/projects/one/worktrees/worktree/validate",
    expect.objectContaining({
      method: "POST",
      body: '{"expected_updated_at":"version"}',
    }),
  );
});
