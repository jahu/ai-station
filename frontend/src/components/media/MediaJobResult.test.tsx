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
function mount(status = "generating", preview?: string) {
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
