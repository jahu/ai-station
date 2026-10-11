import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import type { Run } from "../api";
import CodingReview from "./CodingReview";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("keeps a queued commit in the conversation when asked not to navigate", async () => {
  const queued = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({ id: "commit" }),
    })),
  );
  const run = {
    id: "coding",
    status: "succeeded",
    summary: "Fix selected files",
    metadata: {
      coding_review: {
        branch: "ai/test",
        files: [
          { path: "file.py", diff: "+print(42)", insertions: 1, deletions: 0 },
        ],
      },
    },
  } as unknown as Run;
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <CodingReview run={run} onQueued={queued} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(
    screen.getByRole("button", { name: "Commit reviewed changes" }),
  );
  await vi.waitFor(() => expect(queued).toHaveBeenCalled());
  expect(queued.mock.calls[0][0]).toEqual({ id: "commit" });
  expect(screen.queryByRole("heading", { name: "Commit Run" })).toBeNull();
});
it("requires review acknowledgement and opens the queued commit", async () => {
  const fetch = vi.fn(async () => ({
    ok: true,
    json: async () => ({ id: "commit" }),
  }));
  vi.stubGlobal("fetch", fetch);
  const run = {
    id: "coding",
    status: "succeeded",
    summary: "Fix selected files",
    metadata: {
      coding_review: {
        branch: "ai/test",
        files: [
          { path: "file.py", diff: "+print(42)", insertions: 1, deletions: 0 },
        ],
      },
    },
  } as unknown as Run;
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <Routes>
          <Route path="/" element={<CodingReview run={run} />} />
          <Route path="/runs/:id" element={<h1>Commit Run</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(screen.getByText(/Unique snippet replacements/)).toBeTruthy();
  const button = screen.getByRole("button", {
    name: "Commit reviewed changes",
  });
  expect(button.hasAttribute("disabled")).toBe(true);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(button);
  await screen.findByRole("heading", { name: "Commit Run" });
  expect(fetch).toHaveBeenCalledWith(
    "/api/coding/runs/coding/commit",
    expect.objectContaining({
      body: JSON.stringify({ message: "Fix selected files", reviewed: true }),
    }),
  );
});

it("moves through commit review without queueing a commit", () => {
  const fetch = vi.fn(async () => ({
    ok: true,
    json: async () => ({ id: "commit" }),
  }));
  vi.stubGlobal("fetch", fetch);
  const run = {
    id: "coding",
    status: "succeeded",
    summary: "Fix selected files",
    metadata: {
      coding_review: {
        branch: "ai/test",
        files: [
          { path: "file.py", diff: "+print(42)", insertions: 1, deletions: 0 },
        ],
      },
    },
  } as unknown as Run;
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <CodingReview run={run} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const option = screen.getByLabelText("Review commit");
  expect(option.tabIndex).toBe(0);
  expect(
    screen.getByText(/There is no inspectable review-ack Run/),
  ).toBeTruthy();
  fireEvent.keyDown(option.closest(".review-choice-list") as HTMLElement, {
    key: "Enter",
  });
  expect(
    (
      screen.getByRole("checkbox", {
        name: /I reviewed the diff/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
  expect(JSON.stringify(fetch.mock.calls)).not.toContain("/commit");
});

function validationFetch(
  extra?: Record<string, unknown>,
  events: unknown[] = [],
) {
  return vi.fn(async (path: string, options?: RequestInit) => ({
    ok: true,
    json: async () =>
      options?.method === "POST"
        ? { id: "repair" }
        : String(path).endsWith("/events")
          ? events
          : {
              id: "validation",
              status: "failed",
              error_type: "ValidationFailed",
              ...extra,
            },
  }));
}

it("offers a local repair only after confirmed failing validation", async () => {
  const fetch = validationFetch();
  vi.stubGlobal("fetch", fetch);
  const run = {
    id: "coding",
    executor_type: "local_proposal",
    status: "succeeded",
    metadata: {
      execution_location: "local",
      validation_run_id: "validation",
      coding_review: { branch: "ai/task", files: [] },
    },
  } as unknown as Run;
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <Routes>
          <Route path="/" element={<CodingReview run={run} />} />
          <Route path="/runs/repair" element={<h1>Repair Run</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const repairButton = await screen.findByRole("button", {
    name: "Repair with Local AI",
  });
  expect(
    screen.queryByRole("button", { name: "Commit reviewed changes" }),
  ).toBeNull();
  fireEvent.click(repairButton);
  await screen.findByRole("heading", { name: "Repair Run" });
  expect(fetch).toHaveBeenCalledWith(
    "/api/coding/runs/coding/repair",
    expect.objectContaining({ method: "POST" }),
  );
});

it("shows saved validation commands in the review without inventing a child Run", async () => {
  vi.stubGlobal(
    "fetch",
    validationFetch(undefined, [
      {
        id: "val-test",
        sequence: 1,
        event_type: "validation.completed",
        payload: {
          kind: "test",
          argv: ["pytest", "-q"],
          exit_code: 1,
          duration_seconds: 0.8,
        },
        created_at: "2026-10-11T12:00:00Z",
      },
    ]),
  );
  const run = {
    id: "coding",
    executor_type: "local_proposal",
    status: "succeeded",
    metadata: {
      execution_location: "local",
      validation_run_id: "validation",
      coding_review: {
        branch: "ai/task",
        files: [
          { path: "app.py", diff: "+print(1)", insertions: 1, deletions: 0 },
        ],
      },
    },
  } as unknown as Run;
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <CodingReview run={run} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByLabelText("Command test val-test")).toBeTruthy();
  expect(screen.getByText(/\["pytest","-q"\]/)).toBeTruthy();
  expect(screen.getByText(/There is no inspectable child Run/)).toBeTruthy();
  expect(
    screen
      .getByRole("link", { name: /Validation: failed/ })
      .getAttribute("href"),
  ).toBe("/runs/validation");
  expect(screen.queryByRole("heading", { name: "Commit Run" })).toBeNull();
});

it("links to an existing repair and prevents committing a superseded proposal", async () => {
  vi.stubGlobal("fetch", validationFetch());
  const run = {
    id: "coding",
    executor_type: "local_proposal",
    status: "succeeded",
    metadata: {
      execution_location: "local",
      validation_run_id: "validation",
      repair_run_id: "repair",
      coding_review: {
        branch: "ai/task",
        files: [
          { path: "new.py", diff: "+print(42)", insertions: 1, deletions: 0 },
        ],
      },
    },
  } as unknown as Run;
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <CodingReview run={run} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByText("Validation: failed →");
  expect(
    screen.getByRole("link", { name: "Open repair →" }).getAttribute("href"),
  ).toBe("/runs/repair");
  expect(
    screen.queryByRole("button", { name: "Commit reviewed changes" }),
  ).toBeNull();
  expect(
    screen.queryByRole("button", { name: "Repair with Local AI" }),
  ).toBeNull();
});

it("moves between files with arrow keys and shows only the selected patch", () => {
  const run = {
    id: "coding",
    status: "succeeded",
    metadata: {
      coding_review: {
        branch: "ai/task",
        files: [
          { path: "one.py", diff: "+one", insertions: 1, deletions: 0 },
          { path: "two.py", diff: "+two", insertions: 2, deletions: 1 },
        ],
      },
    },
  } as unknown as Run;
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <CodingReview run={run} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const list = screen.getByRole("listbox", {
    name: /Arrow keys choose a file/,
  });
  expect(
    screen
      .getByRole("option", { name: "File one.py" })
      .getAttribute("aria-selected"),
  ).toBe("true");
  expect(screen.getByLabelText("Diff for one.py")).toBeTruthy();
  expect(screen.queryByLabelText("Diff for two.py")).toBeNull();
  fireEvent.keyDown(list, { key: "ArrowDown" });
  expect(
    screen
      .getByRole("option", { name: "File two.py" })
      .getAttribute("aria-selected"),
  ).toBe("true");
  expect(screen.getByLabelText("Diff for two.py")).toBeTruthy();
  expect(screen.queryByLabelText("Diff for one.py")).toBeNull();
  fireEvent.keyDown(list, { key: "Enter" });
  expect(screen.getByLabelText("Diff for two.py")).toBeTruthy();
  expect(screen.queryByRole("heading", { name: "Commit Run" })).toBeNull();
  fireEvent.keyDown(list, { key: "Home" });
  expect(screen.getByLabelText("Diff for one.py")).toBeTruthy();
});

it("states cumulative totals against the task base", () => {
  const run = {
    id: "repair",
    status: "succeeded",
    parameters: { cumulative: true },
    metadata: {
      repair_source_run_id: "previous",
      coding_review: {
        branch: "ai/task",
        base_commit: "abcdef1234567890",
        files: [
          { path: "app.py", diff: "+x", insertions: 3, deletions: 1 },
          { path: "lib.py", diff: "+y", insertions: 2, deletions: 2 },
        ],
      },
    },
  } as unknown as Run;
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <CodingReview run={run} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(
    screen.getByText(
      /2 files · \+5 \/ −3 · cumulative against the task base · base abcdef123456/,
    ),
  ).toBeTruthy();
  expect(
    screen
      .getByRole("link", { name: "Previous attempt →" })
      .getAttribute("href"),
  ).toBe("/runs/previous");
});

it("offers download and Library actions for the stored patch artifact", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => ({
      ok: true,
      json: async () =>
        String(path).includes("/artifacts?")
          ? [
              {
                id: "patch",
                type: "git_diff",
                original_filename: "changes.diff",
              },
              {
                id: "report",
                type: "json",
                original_filename: "coding-review.json",
              },
            ]
          : [],
    })),
  );
  const run = {
    id: "coding",
    status: "succeeded",
    metadata: {
      coding_review: {
        branch: "ai/task",
        files: [
          { path: "file.py", diff: "+print(42)", insertions: 1, deletions: 0 },
        ],
      },
    },
  } as unknown as Run;
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <CodingReview run={run} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const download = await screen.findByRole("link", { name: "Download patch" });
  expect(download.getAttribute("href")).toBe("/api/artifacts/patch/file");
  expect(download.getAttribute("download")).toBe("changes.diff");
  expect(
    screen
      .getByRole("link", { name: "Open patch in Library →" })
      .getAttribute("href"),
  ).toBe("/library/patch");
  expect(
    screen
      .getByRole("link", { name: "Download review JSON" })
      .getAttribute("href"),
  ).toBe("/api/artifacts/report/file");
});

it("moves through exploration steps with arrow keys without inventing a Run", () => {
  const run = {
    id: "coding",
    status: "succeeded",
    metadata: {
      coding_review: {
        branch: "ai/task",
        exploration: [
          {
            request: { tool: "list_files", path: "." },
            result: { paths: ["one.py"] },
          },
          {
            request: { tool: "read_file", path: "one.py" },
            result: { content: "print(1)" },
          },
        ],
        files: [{ path: "one.py", diff: "+one", insertions: 1, deletions: 0 }],
      },
    },
  } as unknown as Run;
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <CodingReview run={run} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByText(/Repository exploration · 2 steps/));
  const first = screen.getByLabelText("Step 1 list_files");
  const second = screen.getByLabelText("Step 2 read_file");
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(
    screen.getByText(/There is no inspectable exploration Run/),
  ).toBeTruthy();
  fireEvent.keyDown(first.closest(".coding-exploration") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(document.activeElement).toBe(second);
  fireEvent.keyDown(second.closest(".coding-exploration") as HTMLElement, {
    key: "Enter",
  });
  expect(screen.queryByRole("heading", { name: "Commit Run" })).toBeNull();
  expect(screen.getByLabelText("Diff for one.py")).toBeTruthy();
});
