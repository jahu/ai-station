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

it("shows measured active film steps separately from completed segments", () => {
  mount("generating", undefined, {
    active_generation_progress: [
      {
        run_id: "active-segment",
        capability: "video.generate",
        status: "running",
        phase: "generating",
        elapsed_seconds: 30,
        fraction: { completed: 4, total: 20, unit: "sampling steps" },
        estimate: {
          lower_seconds: 90,
          upper_seconds: 120,
          scope: "sampling",
          basis: "observed sampling speed",
        },
      },
    ],
  });
  expect(
    screen
      .getByRole("progressbar", { name: "Video step measured progress" })
      .getAttribute("value"),
  ).toBe("4");
  expect(
    screen
      .getByRole("progressbar", { name: "Completed video stages" })
      .getAttribute("value"),
  ).toBe("2");
  expect(screen.getByText("About 1m 30s – 2m of sampling left")).not.toBeNull();
});

it("shows measured whole-recording animation progress without inventing segments", () => {
  mount("generating", undefined, {
    kind: "avatar",
    mode: "whole_recording",
    total_segments: 0,
    completed_segments: 0,
    total_stages: 1,
    completed_stages: 0,
    native_progress: {
      phase: "animating",
      completed_windows: 210,
      total_windows: 525,
    },
    result_geometry: { width: 512, height: 768, fps: 25 },
  });
  const progress = screen.getByRole("progressbar", {
    name: "Avatar animation progress",
  });
  expect(progress.getAttribute("max")).toBe("525");
  expect(progress.getAttribute("value")).toBe("210");
  expect(
    screen.getByText("Animating the complete recording · 40%"),
  ).toBeTruthy();
  expect(screen.queryByText(/0 of 0/)).toBeNull();
});

it("distinguishes finishing from a verified complete whole-recording result", () => {
  mount("generating", undefined, {
    kind: "avatar",
    mode: "whole_recording",
    total_segments: 0,
    completed_segments: 0,
    native_progress: {
      phase: "finishing",
      completed_windows: 525,
      total_windows: 525,
    },
    estimated_animation_seconds: 100,
  });
  expect(
    screen.getByText("Saving and checking the complete recording…"),
  ).toBeTruthy();
  expect(screen.queryByText("Your full video is ready.")).toBeNull();
  expect(screen.queryByLabelText("Generated full video")).toBeNull();
  expect(screen.queryByLabelText("Estimated animation time")).toBeNull();
});

it("labels a measured animation estimate separately from saving and final verification", () => {
  mount("generating", undefined, {
    kind: "avatar",
    mode: "whole_recording",
    native_progress: {
      phase: "animating",
      completed_windows: 100,
      total_windows: 525,
    },
    estimated_animation_seconds: 8100,
  });
  expect(screen.getByLabelText("Estimated animation time").textContent).toBe(
    "About 2 h 15 min of animation left. Saving and checks follow.",
  );
  expect(screen.queryByText("Your full video is ready.")).toBeNull();
});
it("reports actual segment progress and stops the entire job", async () => {
  const writes = mount();
  expect(screen.getByText("2 of 23 segments complete")).toBeTruthy();
  expect(screen.queryByLabelText("Generated full video")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Stop film" }));
  await vi.waitFor(() =>
    expect(writes[0].url).toBe("/api/media/jobs/task/cancel"),
  );
});

it("distinguishes prompt review from speech preparation or GPU generation", () => {
  const writes = mount("preparing", undefined, {
    kind: "video",
    prompt_preparation_status: "review",
  });
  expect(
    screen.getByText(
      "Review the translated prompts below before film generation.",
    ),
  ).toBeTruthy();
  expect(
    screen.queryByText("Generating speech and preparing its full timeline…"),
  ).toBeNull();
  expect(writes).toHaveLength(0);
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
    completed_segments: 0,
    total_segments: 3,
    running_segments: 2,
    queued_segments: 1,
    active_segments: [
      { run_id: "first", index: 0, status: "running", gpu: "2" },
      { run_id: "second", index: 1, status: "running", gpu: "7" },
    ],
  });
  expect(screen.getByText("2 shots running · 1 queued")).toBeTruthy();
  expect(screen.getByText("0 of 3 shots complete")).toBeTruthy();
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

it("keeps scene readiness separate from final video and inspection starts no work", () => {
  const writes = mount("generating", undefined, {
    mode: "shots",
    scenes: [
      {
        index: 0,
        prompt: "Opening forest",
        duration_seconds: 2,
        status: "succeeded",
        completed_segments: 1,
        total_segments: 1,
      },
      {
        index: 1,
        prompt: "Closing ocean",
        duration_seconds: 4,
        status: "running",
        completed_segments: 1,
        total_segments: 2,
      },
    ],
  });
  fireEvent.click(screen.getByText("1 of 2 scenes ready"));
  expect(screen.getByLabelText("Scene progress")).toBeTruthy();
  expect(screen.getByText("Opening forest")).toBeTruthy();
  expect(screen.getByLabelText("Scene 2 progress").getAttribute("value")).toBe(
    "1",
  );
  expect(screen.getByLabelText("Scene 2 progress").getAttribute("max")).toBe(
    "2",
  );
  expect(screen.queryByLabelText("Generated full video")).toBeNull();
  expect(writes).toHaveLength(0);
});

it("reports a measured memory wait during speech preparation without claiming inference started", () => {
  mount("preparing", undefined, {
    kind: "avatar",
    total_segments: 0,
    completed_segments: 0,
    resource_wait: {
      run_id: "speech",
      reason: "memory",
      checked_at: "2026-10-23T12:00:00Z",
      required_mib: 16384,
      available_mib: 12288,
      reserved_mib: 0,
      headroom_mib: 1024,
    },
  });
  expect(screen.getByText("Waiting for memory")).toBeTruthy();
  expect(
    screen.getByText(
      /Queued; generation will start when resources are available/,
    ),
  ).toBeTruthy();
  expect(screen.queryByText(/Generating speech and preparing/)).toBeNull();
  expect(screen.getByRole("button", { name: "Stop film" })).toBeTruthy();
});

it("hides an old memory observation while stopping the entire job", () => {
  mount("cancel_requested", undefined, {
    resource_wait: {
      run_id: "speech",
      reason: "memory",
      checked_at: "2026-10-23T12:00:00Z",
      required_mib: 16384,
      available_mib: 12288,
      reserved_mib: 0,
      headroom_mib: 1024,
    },
  });
  expect(screen.queryByLabelText("Resource wait")).toBeNull();
});

it("does not promise automatic retry after a composed job failed with remaining children", () => {
  mount("failed", undefined, {
    resource_wait: {
      run_id: "segment",
      reason: "memory",
      checked_at: "2026-10-23T12:00:00Z",
      required_mib: 16384,
      available_mib: 12288,
      reserved_mib: 0,
      headroom_mib: 1024,
    },
  });
  expect(screen.queryByLabelText("Resource wait")).toBeNull();
  expect(screen.getByText("A segment failed")).toBeTruthy();
});

it("reports audio finishing separately after all silent video segments complete", async () => {
  mount("composing", undefined, {
    soundtrack_status: "mixing",
    completed_segments: 23,
    final_artifact_id: null,
  });
  expect(
    (await screen.findByText(/Mixing the film and sound/)).textContent,
  ).toContain("after verification");
  expect(screen.queryByRole("link", { name: /Download/ })).toBeNull();
});
