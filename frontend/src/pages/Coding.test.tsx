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

it("queues local coding with the selected model and no external-AI grant", async () => {
  const fetch = vi.fn(async (path: string, options?: RequestInit) => ({
    ok: true,
    json: async () =>
      options?.method === "POST"
        ? { id: "local-prepare" }
        : path.endsWith("/provider")
          ? { models: ["local-model"], default_model: "local-model" }
          : path.endsWith("/llama")
            ? { models: [], instances: [] }
            : path.endsWith("/hardware")
              ? { gpus: [] }
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
          <Route
            path="/runs/local-prepare"
            element={<h1>Local preparation</h1>}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.change(await screen.findByLabelText("Project"), {
    target: { value: "project" },
  });
  fireEvent.change(screen.getByLabelText("Task"), {
    target: { value: "Update README" },
  });
  fireEvent.click(screen.getByRole("button", { name: /Local AI llama/ }));
  await screen.findByText("local-model");
  expect(
    (
      screen.getByRole("checkbox", {
        name: "Let Local AI find the relevant files",
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
  expect(screen.queryByLabelText("Selected files")).toBeNull();
  expect(
    (
      screen.getByLabelText("Automatic repair", {
        exact: false,
      }) as HTMLSelectElement
    ).value,
  ).toBe("0");
  fireEvent.change(
    screen.getByLabelText("Automatic repair", { exact: false }),
    { target: { value: "2" } },
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Create worktree and start Local AI" }),
  );
  await screen.findByRole("heading", { name: "Local preparation" });
  expect(fetch).toHaveBeenCalledWith(
    "/api/coding/local",
    expect.objectContaining({
      body: JSON.stringify({
        project_id: "project",
        expected_updated_at: "version",
        prompt: "Update README",
        files: [],
        model: "local-model",
        explore: true,
        max_repair_attempts: 2,
      }),
    }),
  );
});
