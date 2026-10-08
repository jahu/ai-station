import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import CodingSession, { CodingNav } from "./CodingSessions";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("reopens task history and sends a guarded follow-up to the same conversation", async () => {
  const task = {
    id: "task",
    title: "Build a site",
    project_name: "Studio",
    status: "succeeded",
    active_run_id: null,
    latest_proposal_id: "proposal",
    runs: [
      {
        id: "proposal",
        task_id: "task",
        executor_type: "codex_proposal",
        status: "succeeded",
        created_at: "2026-10-08T00:00:00Z",
        parameters: { prompt: "Build my homepage" },
        summary: "Homepage created",
        metadata: { execution_location: "external" },
      },
    ],
  };
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () => (path === "/api/coding/sessions" ? [task] : task),
  }));
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={["/coding/task"]}>
        <CodingNav />
        <Routes>
          <Route path="/coding/:id" element={<CodingSession />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByText("Homepage created");
  expect(screen.getByText("Build my homepage")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Follow-up instruction"), {
    target: { value: "Add a contact form" },
  });
  expect(
    (screen.getByRole("button", { name: "Send" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  fireEvent.click(screen.getByRole("checkbox", { name: /Share this turn/ }));
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  await vi.waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/coding/sessions/task/messages",
      expect.objectContaining({
        body: JSON.stringify({
          prompt: "Add a contact form",
          expected_run_id: "proposal",
          external_ai: true,
        }),
      }),
    ),
  );
  expect(
    screen.getByRole("link", { name: /Build a site/ }).getAttribute("href"),
  ).toBe("/coding/task");
});
