import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ProjectAgents from "./ProjectAgents";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function mount(excludeAgentId?: string) {
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={cache}>
      <MemoryRouter initialEntries={["/projects/project-1"]}>
        <Routes>
          <Route
            path="/projects/project-1"
            element={
              <ProjectAgents
                projectId="project-1"
                excludeAgentId={excludeAgentId}
              />
            }
          />
          <Route path="/agents/:id" element={<h1>Agent definition</h1>} />
          <Route path="/agents" element={<h1>Filtered agents</h1>} />
          <Route path="/runs" element={<h1>Tagged Runs</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const row = {
  goal: "Summarize workstation health",
  model: "local",
  enabled: false,
  last_status: "",
  next_run_at: null,
};

it("lists linked agents from GET /api/agents?project_id= without Enable or Run now", async () => {
  const fetch = vi.fn(async (url: string) => ({
    ok: true,
    json: async () =>
      url.includes("project_id=project-1")
        ? [
            { ...row, id: "agentone", name: "Morning review" },
            {
              ...row,
              id: "agenttwo",
              name: "Evening check",
              enabled: true,
              last_status: "succeeded",
            },
          ]
        : [],
  }));
  vi.stubGlobal("fetch", fetch);
  mount();
  await screen.findByRole("link", {
    name: "Inspect agent Morning review agentone",
  });
  expect(fetch).toHaveBeenCalledWith(
    "/api/agents?limit=50&offset=0&project_id=project-1",
    undefined,
  );
  expect(
    screen.getByRole("link", { name: "View all linked agents" }).getAttribute(
      "href",
    ),
  ).toBe("/agents?project_id=project-1");
  expect(
    screen.getByRole("link", { name: "View tagged Runs agentone" }).getAttribute(
      "href",
    ),
  ).toBe("/runs?project_id=project-1&agent_id=agentone");
  expect(
    screen.getAllByText(/does not grant coding, Git or repository access/)
      .length,
  ).toBeGreaterThan(0);
  expect(screen.queryByRole("button", { name: /Enable/i })).toBeNull();
  expect(screen.queryByRole("button", { name: /Run now/i })).toBeNull();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/enabled")),
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
  fireEvent.click(
    screen.getByRole("link", {
      name: "Inspect agent Morning review agentone",
    }),
  );
  await screen.findByRole("heading", { name: "Agent definition" });
});

it("moves through linked agents with arrow keys", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => [
        { ...row, id: "agentone", name: "Morning review" },
        { ...row, id: "agenttwo", name: "Evening check" },
      ],
    })),
  );
  mount();
  const first = await screen.findByRole("link", {
    name: "Inspect agent Morning review agentone",
  });
  const second = screen.getByRole("link", {
    name: "Inspect agent Evening check agenttwo",
  });
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(screen.getByRole("region", { name: "Linked agents" })).toBeTruthy();
  fireEvent.keyDown(first.closest(".worktree-list") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  expect(document.activeElement).toBe(
    screen
      .getByRole("link", {
        name: "Inspect agent Evening check agenttwo",
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
  await screen.findByRole("heading", { name: "Agent definition" });
});

it("omits the current agent when listing siblings on a definition", async () => {
  const fetch = vi.fn(async (url: string) => ({
    ok: true,
    json: async () =>
      url.includes("project_id=project-1")
        ? [
            { ...row, id: "agentone", name: "Morning review" },
            { ...row, id: "agenttwo", name: "Evening check" },
          ]
        : [],
  }));
  vi.stubGlobal("fetch", fetch);
  mount("agentone");
  expect(
    await screen.findByRole("link", {
      name: "Inspect agent Evening check agenttwo",
    }),
  ).toBeTruthy();
  expect(
    screen.getByRole("heading", { name: "Other agents on this project" }),
  ).toBeTruthy();
  expect(
    screen.queryByRole("link", {
      name: "Inspect agent Morning review agentone",
    }),
  ).toBeNull();
  expect(screen.queryByRole("button", { name: /Enable/i })).toBeNull();
  expect(screen.queryByRole("button", { name: /Run now/i })).toBeNull();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/enabled")),
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});

it("shows an empty state when no agents tag this project", async () => {
  const fetch = vi.fn(async (url: string) => ({
    ok: true,
    json: async () => (url.includes("project_id=project-1") ? [] : [{ ...row, id: "other" }]),
  }));
  vi.stubGlobal("fetch", fetch);
  mount();
  expect(await screen.findByText("No linked agents")).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "View all linked agents" }).getAttribute(
      "href",
    ),
  ).toBe("/agents?project_id=project-1");
  expect(screen.queryByRole("link", { name: /Inspect agent/ })).toBeNull();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/enabled")),
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});
