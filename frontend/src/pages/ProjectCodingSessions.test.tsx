import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ProjectCodingSessions from "./ProjectCodingSessions";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function mount() {
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={cache}>
      <MemoryRouter initialEntries={["/projects/project-1"]}>
        <Routes>
          <Route
            path="/projects/project-1"
            element={<ProjectCodingSessions projectId="project-1" />}
          />
          <Route path="/coding/:id" element={<h1>Open conversation</h1>} />
          <Route path="/coding" element={<h1>Filtered conversations</h1>} />
          <Route path="/runs" element={<h1>Tagged Runs</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const row = {
  status: "succeeded",
  updated_at: "2026-10-12T00:00:00Z",
};

it("lists coding conversations from GET /api/coding/sessions?project_id= without starting a Run", async () => {
  const fetch = vi.fn(async (url: string) => ({
    ok: true,
    json: async () =>
      url.includes("project_id=project-1")
        ? [
            { ...row, id: "sess-one", title: "Build a site" },
            { ...row, id: "sess-two", title: "Fix the form" },
          ]
        : [],
  }));
  vi.stubGlobal("fetch", fetch);
  mount();
  await screen.findByRole("link", {
    name: "Inspect Build a site sess-one",
  });
  expect(fetch).toHaveBeenCalledWith(
    "/api/coding/sessions?limit=50&offset=0&project_id=project-1",
    undefined,
  );
  expect(
    screen
      .getByRole("link", { name: "View all coding conversations" })
      .getAttribute("href"),
  ).toBe("/coding?project_id=project-1");
  expect(
    screen
      .getByRole("link", { name: "Inspect Build a site sess-one" })
      .getAttribute("href"),
  ).toBe("/coding/sess-one");
  expect(
    screen
      .getByRole("link", { name: "View tagged Runs sess-one" })
      .getAttribute("href"),
  ).toBe("/runs?project_id=project-1");
  expect(
    screen
      .getByRole("link", { name: "View tagged Runs sess-two" })
      .getAttribute("href"),
  ).toBe("/runs?project_id=project-1");
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).includes("/coding/cursor")),
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).includes("/messages")),
  ).toBe(true);
  fireEvent.click(
    screen.getByRole("link", {
      name: "Inspect Build a site sess-one",
    }),
  );
  await screen.findByRole("heading", { name: "Open conversation" });
});

it("opens tagged project Runs from a coding conversation row without starting a Run", async () => {
  const fetch = vi.fn(async (url: string, options?: RequestInit) => ({
    ok: true,
    json: async () =>
      options?.method === "POST"
        ? { id: "unexpected" }
        : url.includes("project_id=project-1")
          ? [{ ...row, id: "sess-one", title: "Build a site" }]
          : [],
  }));
  vi.stubGlobal("fetch", fetch);
  mount();
  expect(
    (
      await screen.findByRole("link", { name: "View tagged Runs sess-one" })
    ).getAttribute("href"),
  ).toBe("/runs?project_id=project-1");
  expect(
    screen.getByRole("link", { name: "Inspect Build a site sess-one" }),
  ).toBeTruthy();
  expect(screen.queryByRole("button", { name: /Enable/i })).toBeNull();
  expect(screen.queryByRole("button", { name: /Run now/i })).toBeNull();
  fireEvent.click(
    screen.getByRole("link", { name: "View tagged Runs sess-one" }),
  );
  await screen.findByRole("heading", { name: "Tagged Runs" });
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).includes("/coding/cursor")),
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).includes("/messages")),
  ).toBe(true);
  expect(
    fetch.mock.calls.filter(([, options]) => options?.method === "POST"),
  ).toHaveLength(0);
});

it("moves through project coding conversations with arrow keys", async () => {
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
  mount();
  const first = await screen.findByRole("link", {
    name: "Inspect Build a site sess-one",
  });
  const second = screen.getByRole("link", {
    name: "Inspect Fix the form sess-two",
  });
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(
    screen.getByRole("link", { name: "View tagged Runs sess-one" }).tabIndex,
  ).toBe(0);
  expect(
    screen.getByRole("link", { name: "View tagged Runs sess-two" }).tabIndex,
  ).toBe(-1);
  expect(
    screen.getByRole("region", { name: "Coding conversations" }),
  ).toBeTruthy();
  fireEvent.keyDown(first.closest(".worktree-list") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  expect(
    screen.getByRole("link", { name: "View tagged Runs sess-two" }).tabIndex,
  ).toBe(0);
  expect(
    screen.getByRole("link", { name: "View tagged Runs sess-one" }).tabIndex,
  ).toBe(-1);
  expect(document.activeElement).toBe(
    screen
      .getByRole("link", {
        name: "Inspect Fix the form sess-two",
      })
      .closest("[data-list-index]"),
  );
  fireEvent.keyDown(second.closest(".worktree-list") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
  fireEvent.keyDown(first.closest(".worktree-list") as HTMLElement, {
    key: "Enter",
  });
  await screen.findByRole("heading", { name: "Open conversation" });
});

it("shows an empty state when no coding conversations tag this project", async () => {
  const fetch = vi.fn(async (url: string) => ({
    ok: true,
    json: async () => (url.includes("project_id=project-1") ? [] : [{ ...row, id: "other" }]),
  }));
  vi.stubGlobal("fetch", fetch);
  mount();
  expect(await screen.findByText("No coding conversations")).toBeTruthy();
  expect(
    screen
      .getByRole("link", { name: "View all coding conversations" })
      .getAttribute("href"),
  ).toBe("/coding?project_id=project-1");
  expect(screen.queryByRole("link", { name: /Inspect / })).toBeNull();
  expect(screen.queryByRole("link", { name: /View tagged Runs/ })).toBeNull();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).includes("/coding/cursor")),
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).includes("/messages")),
  ).toBe(true);
});
