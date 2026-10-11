import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import CodingSession, { CodingHistory, CodingNav } from "./CodingSessions";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("reopens task history and sends a guarded follow-up to the same conversation", async () => {
  const task = {
    id: "task",
    title: "Build a site",
    project_id: "project-1",
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
  expect(
    screen.getByRole("link", { name: "Inspect project project-1" }).getAttribute(
      "href",
    ),
  ).toBe("/projects/project-1");
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

it("moves through follow-up consent without starting a Run", async () => {
  const task = {
    id: "task",
    title: "Build a site",
    project_id: "project-1",
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
        <Routes>
          <Route path="/coding/:id" element={<CodingSession />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const option = await screen.findByLabelText("Consent external_ai");
  expect(option.tabIndex).toBe(0);
  expect(screen.getByText(/There is no inspectable consent Run/)).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Follow-up instruction"), {
    target: { value: "Add a contact form" },
  });
  fireEvent.keyDown(option.closest(".consent-choice-list") as HTMLElement, {
    key: "Enter",
  });
  expect(
    (
      screen.getByRole("checkbox", { name: /Share this turn/ }) as HTMLInputElement
    ).checked,
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).includes("/messages")),
  ).toBe(true);
});

it("opens the project from a coding conversation without starting a Run", async () => {
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      path.includes("/coding/sessions")
        ? [
            {
              id: "sess-one",
              title: "Build a site",
              project_id: "project-1",
              project_name: "Studio",
              status: "succeeded",
              active_run_id: null,
              latest_proposal_id: "proposal",
            },
          ]
        : [],
  }));
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <CodingHistory />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(
    (
      await screen.findByRole("link", { name: "Inspect project project-1" })
    ).getAttribute("href"),
  ).toBe("/projects/project-1");
  expect(
    screen.getByRole("link", { name: "Inspect project project-1" }).textContent,
  ).toBe("Studio");
  expect(
    screen
      .getByRole("link", { name: "Inspect Build a site sess-one" })
      .getAttribute("href"),
  ).toBe("/coding/sess-one");
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).includes("/coding/cursor")),
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).includes("/messages")),
  ).toBe(true);
});

it("filters coding conversations by project without starting a Run", async () => {
  const row = {
    project_name: "Studio",
    status: "succeeded",
    active_run_id: null,
    latest_proposal_id: "proposal",
  };
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () => {
      if (path.includes("/projects")) {
        return [
          { id: "project-1", name: "Studio" },
          { id: "project-2", name: "Other" },
        ];
      }
      if (path.includes("project_id=project-1")) {
        return [
          {
            ...row,
            id: "sess-one",
            title: "Build a site",
            project_id: "project-1",
          },
        ];
      }
      if (path.includes("/coding/sessions")) {
        return [
          {
            ...row,
            id: "sess-one",
            title: "Build a site",
            project_id: "project-1",
          },
          {
            ...row,
            id: "sess-two",
            title: "Fix the form",
            project_id: "project-2",
            project_name: "Other",
          },
        ];
      }
      return [];
    },
  }));
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <CodingHistory />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(
    await screen.findByRole("link", { name: "Inspect Fix the form sess-two" }),
  ).toBeTruthy();
  fireEvent.change(screen.getByRole("combobox", { name: "Filter project" }), {
    target: { value: "project-1" },
  });
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/coding/sessions?project_id=project-1",
      undefined,
    ),
  );
  expect(
    await screen.findByRole("link", { name: "Inspect Build a site sess-one" }),
  ).toBeTruthy();
  expect(
    screen.queryByRole("link", { name: "Inspect Fix the form sess-two" }),
  ).toBeNull();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).includes("/coding/cursor")),
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).includes("/messages")),
  ).toBe(true);
});

it("moves through coding conversations with arrow keys", async () => {
  const row = {
    project_name: "Studio",
    status: "succeeded",
    active_run_id: null,
    latest_proposal_id: "proposal",
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => [
        { ...row, id: "sess-one", title: "Build a site" },
        { ...row, id: "sess-two", title: "Fix the form" },
      ],
    })),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <CodingHistory />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const first = await screen.findByRole("link", {
    name: "Inspect Build a site sess-one",
  });
  const second = screen.getByRole("link", {
    name: "Inspect Fix the form sess-two",
  });
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(
    screen.getByRole("region", { name: "Coding conversations" }),
  ).toBeTruthy();
  fireEvent.keyDown(first.closest(".coding-history") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  expect(document.activeElement).toBe(
    screen
      .getByRole("link", {
        name: "Inspect Fix the form sess-two",
      })
      .closest("[data-list-index]"),
  );
  fireEvent.keyDown(second.closest(".coding-history") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
});
