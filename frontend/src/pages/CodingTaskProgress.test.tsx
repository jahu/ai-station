import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import type { Run } from "../api";
import CodingTaskProgress from "./CodingTaskProgress";

afterEach(cleanup);
const run = (
  id: string,
  executor_type: string,
  status = "succeeded",
  updates: Partial<Run> = {},
) =>
  ({
    id,
    executor_type,
    status,
    created_at: "2026-10-15T10:00:00Z",
    parameters: {},
    metadata: {},
    ...updates,
  }) as Run;
function show(runs: Run[]) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <CodingTaskProgress runs={runs} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return screen.getByRole("region", { name: "Task progress" });
}
function proposal(updates: Partial<Run> = {}) {
  return run("code", "local_proposal", "succeeded", {
    parameters: {
      worktree_run_id: "workspace",
      project_check_policy: {
        auto_install_dependencies: true,
        auto_validate: true,
      },
      model_selection: { name: "Installed GGUF", context_size: 131072 },
    },
    metadata: {
      project_plan_run_id: "plan",
      dependency_run_ids: ["deps"],
      validation_run_id: "checks",
    },
    ...updates,
  });
}

it("keeps code generation separate from running checks", () => {
  const section = show([
    run("workspace", "worktree_prepare"),
    proposal(),
    run("plan", "project_plan"),
    run("deps", "project_dependencies"),
    run("checks", "project_validation", "running"),
  ]);
  expect(
    within(section).getByRole("heading", { name: "Running project checks" }),
  ).toBeTruthy();
  expect(within(section).queryByText(/ready for review/)).toBeNull();
  expect(within(section).getByText(/131,072 context/)).toBeTruthy();
  expect(
    within(section)
      .getByRole("link", { name: "Inspect checks" })
      .getAttribute("href"),
  ).toBe("/runs/checks");
});

it("reports readiness only after the latest validation succeeds", () => {
  const section = show([
    run("old", "local_proposal", "failed"),
    run("workspace", "worktree_prepare"),
    proposal(),
    run("plan", "project_plan"),
    run("deps", "project_dependencies"),
    run("checks", "project_validation"),
  ]);
  expect(
    within(section).getByRole("heading", {
      name: "Checks passed · ready for review",
    }),
  ).toBeTruthy();
  expect(within(section).queryByText("Task needs attention")).toBeNull();
});

it("shows the dependency failure before blocked checks", () => {
  const section = show([
    proposal(),
    run("plan", "project_plan"),
    run("deps", "project_dependencies", "failed", {
      error_message: "Locked dependency could not be installed",
    }),
    run("checks", "project_validation", "failed", {
      error_message: "Prerequisite failed",
    }),
  ]);
  expect(
    within(section).getByRole("heading", { name: "Task needs attention" }),
  ).toBeTruthy();
  expect(
    within(section).getByText("Locked dependency could not be installed"),
  ).toBeTruthy();
  expect(
    within(section)
      .getByRole("link", { name: "Inspect dependencies" })
      .getAttribute("href"),
  ).toBe("/runs/deps");
});

it("calls an unvalidated proposal untested", () => {
  const section = show([run("code", "cursor_proposal", "succeeded")]);
  expect(
    within(section).getByRole("heading", {
      name: "Changes ready · not tested",
    }),
  ).toBeTruthy();
  expect(within(section).getByText("Not configured")).toBeTruthy();
  expect(within(section).queryByText(/Local ·/)).toBeNull();
});

it("reflects an owned model load while code waits", () => {
  const section = show([
    run("code", "local_proposal", "queued"),
    run("model", "llama_load", "running"),
  ]);
  expect(
    within(section).getByRole("heading", { name: "Loading local model" }),
  ).toBeTruthy();
  expect(
    within(section)
      .getByRole("link", { name: "Inspect local model" })
      .getAttribute("href"),
  ).toBe("/runs/model");
});

it("keeps queued work and approval distinct from execution", () => {
  const section = show([run("code", "local_proposal", "waiting_for_approval")]);
  expect(
    within(section).getByRole("heading", { name: "Approval needed" }),
  ).toBeTruthy();
  cleanup();
  show([run("code", "local_proposal", "queued")]);
  expect(screen.getByRole("heading", { name: "Task queued" })).toBeTruthy();
});

it("shows Stop during execution and canceled dependent stages", () => {
  show([proposal(), run("checks", "project_validation", "cancel_requested")]);
  expect(screen.getByRole("heading", { name: "Stopping task" })).toBeTruthy();
  cleanup();
  show([proposal(), run("checks", "project_validation", "canceled")]);
  expect(screen.getByRole("heading", { name: "Task stopped" })).toBeTruthy();
  expect(
    screen.getByText("Your workspace and conversation are preserved."),
  ).toBeTruthy();
});

it("does not report success while reviewed publication is active", () => {
  show([
    proposal(),
    run("checks", "project_validation"),
    run("publish", "github_publication", "running"),
  ]);
  expect(
    screen.getByRole("heading", { name: "Publishing reviewed changes" }),
  ).toBeTruthy();
  expect(screen.queryByText("Checks passed · ready for review")).toBeNull();
});

it("reports workspace failure even before a proposal exists", () => {
  show([
    run("workspace", "worktree_prepare", "failed", {
      error_message: "Worktree could not be created",
    }),
  ]);
  expect(
    screen.getByRole("heading", { name: "Task needs attention" }),
  ).toBeTruthy();
  expect(screen.getByText("Worktree could not be created")).toBeTruthy();
});

it("does not present a build-only validation as automated test coverage", () => {
  show([
    proposal(),
    run("checks", "project_validation", "succeeded", {
      metadata: { validation: { commands: [{ kind: "build", exit_code: 0 }] } },
    }),
  ]);
  expect(screen.getByText(/No automated tests were recorded/)).toBeTruthy();
});

it("shows a running model load before its queued consumer", () => {
  show([
    run("model", "llama_load", "running"),
    run("code", "local_proposal", "queued"),
  ]);
  expect(
    screen.getByRole("heading", { name: "Loading local model" }),
  ).toBeTruthy();
});
