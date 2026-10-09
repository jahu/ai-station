import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { NewProject, ProjectDetail, Projects } from "./Projects";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function mount(element: React.ReactNode, path: string) {
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={cache}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/projects/new" element={element} />
          <Route path="/coding" element={<h1>Registered repository</h1>} />
          <Route
            path="/projects/:id"
            element={
              path.endsWith("/new") ? <h1>Registered repository</h1> : element
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("requires structured commands and registers only after explicit submission", async () => {
  const fetch = vi.fn(async () => ({
    ok: true,
    json: async () => ({ id: "saved" }),
  }));
  vi.stubGlobal("fetch", fetch);
  mount(<NewProject />, "/projects/new");
  fireEvent.click(
    screen.getByRole("button", { name: "Connect existing repository" }),
  );
  fireEvent.change(screen.getByLabelText("Project name"), {
    target: { value: "AI Station" },
  });
  fireEvent.change(screen.getByLabelText(/Repository path on host/), {
    target: { value: "/repos/station" },
  });
  fireEvent.click(screen.getByText("Validation commands and agent guidance"));
  fireEvent.change(screen.getByLabelText("Test commands"), {
    target: { value: "pytest -q" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Validate and register" }),
  );
  await screen.findByRole("alert");
  expect(fetch).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Test commands"), {
    target: { value: '["pytest", "-q"]' },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Validate and register" }),
  );
  await screen.findByRole("heading", { name: "Registered repository" });
  const options = fetch.mock.calls[0] as unknown as [string, RequestInit];
  expect(options[0]).toBe("/api/projects");
  expect(JSON.parse(options[1].body as string)).toMatchObject({
    repo_path: "/repos/station",
    test_commands: [["pytest", "-q"]],
    pr_policy: { force_push: false, automatic_merge: false },
  });
});

it("keeps saved settings visible when live Git inspection is unavailable", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => ({
      ok: !path.endsWith("/status"),
      json: async () =>
        path.endsWith("/status")
          ? { detail: "Host Runner is unavailable" }
          : path.endsWith("/worktrees")
            ? []
            : {
                id: "saved",
                name: "Saved project",
                repo_path: "/repos/saved",
                default_branch: "main",
                integration_branch: "develop",
                protected_branches: ["main", "master"],
                preferred_executor: "codex",
                test_commands: [],
                lint_commands: [],
                build_commands: [],
                agent_rules: "Preserve the API",
                pr_policy: {},
                updated_at: "2026-09-24T12:00:00Z",
              },
    })),
  );
  mount(<ProjectDetail />, "/projects/saved");
  await screen.findByText("Host Runner is unavailable");
  expect(
    (screen.getByLabelText("Agent rules") as HTMLTextAreaElement).value,
  ).toBe("Preserve the API");
  expect(screen.queryByText("Clean")).toBeNull();
});

it("moves through the project list with arrow keys", async () => {
  const row = {
    repo_path: "/repos/example",
    default_branch: "main",
    integration_branch: "develop",
    protected_branches: ["main", "master"],
    preferred_executor: "codex",
    test_commands: [],
    lint_commands: [],
    build_commands: [],
    agent_rules: "",
    pr_policy: {},
    updated_at: "2026-10-09T12:00:00Z",
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => [
        { ...row, id: "proj-one", name: "Studio site" },
        { ...row, id: "proj-two", name: "Local tools" },
      ],
    })),
  );
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={cache}>
      <MemoryRouter initialEntries={["/projects"]}>
        <Routes>
          <Route path="/projects" element={<Projects />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const first = await screen.findByRole("link", {
    name: "Inspect Studio site proj-one",
  });
  const second = screen.getByRole("link", {
    name: "Inspect Local tools proj-two",
  });
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(screen.getByRole("region", { name: "Projects" })).toBeTruthy();
  fireEvent.keyDown(first.closest(".project-grid") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  expect(document.activeElement).toBe(second);
  fireEvent.keyDown(second.closest(".project-grid") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
});

it("creates a project using only a name and waits for setup", async () => {
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      path === "/api/projects/create"
        ? { id: "setup" }
        : { id: "setup", status: "succeeded", project_id: "new-project" },
  }));
  vi.stubGlobal("fetch", fetch);
  mount(<NewProject />, "/projects/new");
  expect(screen.queryByLabelText(/Repository path/)).toBeNull();
  fireEvent.change(screen.getByLabelText("Project name"), {
    target: { value: "My idea" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Create project" }));
  await screen.findByRole("heading", { name: "Registered repository" });
  expect(fetch).toHaveBeenCalledWith(
    "/api/projects/create",
    expect.objectContaining({ body: JSON.stringify({ name: "My idea" }) }),
  );
});
