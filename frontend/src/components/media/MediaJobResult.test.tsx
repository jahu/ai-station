import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import MediaJobResult from "./MediaJobResult";
import { jobBusy, type MediaJob } from "./media-job";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  sessionStorage.clear();
});
function mount(
  status = "generating",
  preview?: string,
  overrides: Partial<MediaJob> = {},
) {
  const writes: { url: string; body?: Record<string, unknown> }[] = [];
  const job: MediaJob = {
    task_id: "task",
    preview_artifact_id: preview,
    revision: 1,
    status,
    kind: "video",
    mode: "continuous",
    duration_seconds: 60,
    completed_segments: 2,
    total_segments: 23,
    final_artifact_id: null,
    active_run_ids: ["segment"],
    resume_allowed: status === "failed",
    error_message: status === "failed" ? "A segment failed" : "",
    ...overrides,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST")
        writes.push({
          url,
          body: init.body ? JSON.parse(String(init.body)) : undefined,
        });
      return {
        ok: true,
        json: async () =>
          init?.method === "POST"
            ? { ...job, revision: 2, status: "queued" }
            : job,
      };
    }),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <MediaJobResult id="task" job={job} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return writes;
}
it("reports actual segment progress and stops the entire job", async () => {
  const writes = mount();
  expect(screen.getByText("2 of 23 segments complete")).toBeTruthy();
  expect(screen.queryByLabelText("Generated full video")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Stop film" }));
  await vi.waitFor(() =>
    expect(writes[0].url).toBe("/api/media/jobs/task/cancel"),
  );
});
it("resumes unfinished work using the displayed revision and a UUID receipt", async () => {
  const writes = mount("failed");
  fireEvent.click(
    screen.getByRole("button", { name: "Resume unfinished work" }),
  );
  await vi.waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0].body?.expected_revision).toBe(1);
  expect(writes[0].body?.client_request_id).toMatch(/^[0-9a-f-]{36}$/);
  expect(writes[0].url).toBe("/api/media/jobs/task/resume");
});

it("keeps polling failed jobs until dependent stages stop, so Resume can appear", () => {
  expect(
    jobBusy({ status: "failed", active_run_ids: ["dependent"] } as MediaJob),
  ).toBe(true);
  expect(
    jobBusy({ status: "failed", active_run_ids: [] } as unknown as MediaJob),
  ).toBe(false);
});

it("shows one labeled partial preview without presenting it as the final movie", async () => {
  mount("generating", "clip");
  expect(
    screen.getByLabelText("Latest completed segment").getAttribute("src"),
  ).toBe("/api/artifacts/clip/file");
  expect(
    screen.getByText("Latest completed segment · partial preview"),
  ).toBeTruthy();
  expect(screen.queryByLabelText("Generated full video")).toBeNull();
});

it("shows simultaneous shot counts and actual devices without starting work on inspection", async () => {
  const writes = mount("generating", undefined, {
    mode: "shots",
    running_segments: 2,
    queued_segments: 1,
    active_segments: [
      { run_id: "first", index: 0, status: "running", gpu: "2" },
      { run_id: "second", index: 1, status: "running", gpu: "7" },
    ],
  });
  expect(screen.getByText("2 shots running · 1 queued")).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "Shot 1" }).getAttribute("href"),
  ).toBe("/runs/first");
  expect(
    screen.getByRole("link", { name: "Shot 2" }).getAttribute("href"),
  ).toBe("/runs/second");
  expect(screen.getByText("GPU 2")).toBeTruthy();
  expect(screen.getByText("GPU 7")).toBeTruthy();
  expect(screen.queryByLabelText("Generated full video")).toBeNull();
  fireEvent.click(screen.getByRole("link", { name: "Shot 2" }));
  expect(writes).toHaveLength(0);
});

it("keeps resource waiting separate from generating and never invents a GPU", () => {
  mount("queued", undefined, {
    mode: "shots",
    running_segments: 0,
    queued_segments: 3,
    active_segments: [],
  });
  expect(
    screen.getByText("Waiting for available resources · 3 queued"),
  ).toBeTruthy();
  expect(screen.queryByLabelText("Active shots")).toBeNull();
  expect(screen.queryByText(/GPU/)).toBeNull();
});

it("shows preparing and stopping shot state without calling it generation", () => {
  mount("cancel_requested", undefined, {
    mode: "shots",
    running_segments: 0,
    queued_segments: 0,
    active_segments: [
      { run_id: "first", index: 0, status: "cancel_requested", gpu: "7" },
    ],
  });
  expect(screen.getByText("Stopping active shots…")).toBeTruthy();
  expect(
    screen.getByRole("button", { name: "Stop film" }).hasAttribute("disabled"),
  ).toBe(true);
});
