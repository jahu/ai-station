import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import type { Run } from "../api";
import GithubPublication from "./GithubPublication";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function mount(run: Run) {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <Routes>
          <Route path="/" element={<GithubPublication run={run} />} />
          <Route path="/runs/publish" element={<h1>Publication Run</h1>} />
          <Route path="/runs/reconcile" element={<h1>Reconcile Run</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
it("requires approval for the exact repository and commit before publication", async () => {
  const fetch = vi.fn(async (_url: string, options?: RequestInit) => ({
    ok: true,
    json: async () =>
      options
        ? { id: "publish" }
        : {
            repository: "owner/repo",
            branch: "ai/task",
            commit: "abc",
            base: "develop",
            expected_updated_at: "version",
            project_id: "project",
            github_cli_available: true,
            blocked_reason: null,
          },
  }));
  vi.stubGlobal("fetch", fetch);
  mount({
    id: "commit",
    executor_type: "reviewed_commit",
    status: "succeeded",
    metadata: {},
  } as Run);
  const button = await screen.findByRole("button", {
    name: "Publish branch and create draft PR",
  });
  expect(button.hasAttribute("disabled")).toBe(true);
  expect(screen.getByText("owner/repo")).toBeTruthy();
  expect(fetch.mock.calls.filter((call) => call[1])).toHaveLength(0);
  fireEvent.change(screen.getByLabelText("PR title"), {
    target: { value: "Improve feature" },
  });
  fireEvent.change(screen.getByLabelText("PR description"), {
    target: { value: "Tests passed.\nReview details." },
  });
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.change(screen.getByLabelText("PR title"), {
    target: { value: "Updated reviewed feature" },
  });
  expect(button.hasAttribute("disabled")).toBe(true);
  fireEvent.change(screen.getByLabelText("PR title"), {
    target: { value: "Improve feature" },
  });
  fireEvent.click(button);
  await screen.findByRole("heading", { name: "Publication Run" });
  expect(fetch).toHaveBeenCalledWith(
    "/api/coding/runs/commit/publication",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        approved: true,
        repository: "owner/repo",
        commit: "abc",
        base: "develop",
        expected_updated_at: "version",
        title: "Improve feature",
        body: "Tests passed.\nReview details.",
      }),
    }),
  );
});
it("keeps partial failures inspectable without claiming a PR exists", () => {
  mount({
    id: "publish",
    executor_type: "github_publication",
    status: "failed",
    parameters: {
      repository: "owner/repo",
      branch: "ai/task",
      base: "develop",
      commit: "abc",
    },
    metadata: { publication_progress: { stage: "pr_requested" } },
  } as unknown as Run);
  expect(screen.getByText("Last recorded step: pr requested")).toBeTruthy();
  expect(
    screen
      .getByRole("link", { name: "Inspect the repository ↗" })
      .getAttribute("href"),
  ).toBe("https://github.com/owner/repo");
  expect(
    screen.queryByRole("link", { name: "Open draft pull request ↗" }),
  ).toBeNull();
  expect(
    screen.getByRole("button", { name: "Reconcile with GitHub" }),
  ).toBeTruthy();
});

it("queues GitHub reconciliation without claiming a PR exists", async () => {
  const fetch = vi.fn(async () => ({
    ok: true,
    json: async () => ({ id: "reconcile" }),
  }));
  vi.stubGlobal("fetch", fetch);
  mount({
    id: "publish",
    executor_type: "github_publication",
    status: "failed",
    parameters: {
      repository: "owner/repo",
      branch: "ai/task",
      base: "develop",
      commit: "abc",
    },
    metadata: { publication_progress: { stage: "pr_requested" } },
  } as unknown as Run);
  fireEvent.click(
    screen.getByRole("button", { name: "Reconcile with GitHub" }),
  );
  await screen.findByRole("heading", { name: "Reconcile Run" });
  expect(fetch).toHaveBeenCalledWith(
    "/api/coding/runs/publish/reconcile",
    expect.objectContaining({ method: "POST" }),
  );
});
