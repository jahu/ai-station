import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import GenerationProgress, { MediaRunProgress } from "./GenerationProgress";
import type { GenerationProgress as Observation, Run } from "../../api";

afterEach(cleanup);
const measured: Observation = {
  phase: "generating",
  fraction: { completed: 4, total: 8, unit: "sampling steps" },
  elapsed_seconds: 50,
  estimate: {
    lower_seconds: 28,
    upper_seconds: 52,
    basis: "observed sampling speed",
    scope: "sampling",
  },
};
const basicRun: Run = {
  id: "run",
  project_id: null,
  task_id: "task",
  parent_run_id: null,
  capability: "image.generate",
  executor_type: "photo_pipe",
  execution_target: "host",
  status: "running",
  created_at: "2026-10-30T12:00:00Z",
  started_at: null,
  finished_at: null,
  actual_gpu: "7",
  requested_gpu: "auto",
  parameters: {},
  effective_permissions: [],
  summary: "",
  error_type: "",
  error_message: "",
  worker_id: null,
};

it("shows actual units and a clearly scoped sampling estimate", () => {
  render(
    <GenerationProgress progress={measured} status="running" label="Image" />,
  );
  const bar = screen.getByRole("progressbar", {
    name: "Image measured progress",
  });
  expect(bar.getAttribute("value")).toBe("4");
  expect(bar.getAttribute("max")).toBe("8");
  expect(bar.getAttribute("aria-valuetext")).toBe("4 of 8 sampling steps");
  expect(screen.getByText("About 28s – 52s of sampling left")).not.toBeNull();
  expect(
    screen.getByText(
      "Measured from this generation. Saving and checks follow.",
    ),
  ).not.toBeNull();
});

it("keeps queue and saving indeterminate without showing completion", () => {
  const { rerender } = render(
    <GenerationProgress
      progress={{
        ...measured,
        phase: "queued",
        fraction: null,
        estimate: null,
      }}
      status="queued"
    />,
  );
  expect(screen.getByRole("progressbar").hasAttribute("value")).toBe(false);
  expect(
    screen.getByText("Time estimate starts after execution begins."),
  ).not.toBeNull();
  rerender(
    <GenerationProgress
      progress={{
        ...measured,
        phase: "finishing",
        fraction: null,
        estimate: null,
      }}
      status="running"
    />,
  );
  expect(screen.getByRole("progressbar").hasAttribute("value")).toBe(false);
  expect(
    screen.getByText("The result is still being saved and checked."),
  ).not.toBeNull();
  expect(screen.queryByText("Ready")).toBeNull();
});

it("hides stale or invalid estimates and suppresses ETA on Stop", () => {
  const { rerender } = render(
    <GenerationProgress
      progress={{ ...measured, estimate: null, fraction: null }}
      status="running"
    />,
  );
  expect(screen.queryByLabelText("Estimated remaining time")).toBeNull();
  rerender(
    <GenerationProgress
      progress={{
        ...measured,
        estimate: { ...measured.estimate!, upper_seconds: Number.NaN },
      }}
      status="running"
    />,
  );
  expect(screen.queryByLabelText("Estimated remaining time")).toBeNull();
  rerender(
    <GenerationProgress progress={measured} status="cancel_requested" />,
  );
  expect(screen.getByText("Stopping generation…")).not.toBeNull();
  expect(screen.getByRole("progressbar").hasAttribute("value")).toBe(false);
  expect(screen.queryByLabelText("Estimated remaining time")).toBeNull();
});

it("identifies estimates learned from comparable completed jobs", () => {
  render(
    <GenerationProgress
      status="running"
      progress={{
        ...measured,
        phase: "preparing",
        fraction: null,
        estimate: {
          lower_seconds: 60,
          upper_seconds: 100,
          scope: "this stage",
          basis: "similar completed jobs",
          samples: 3,
        },
      }}
    />,
  );
  expect(screen.getByText("About 1m – 1m 40s for this step")).not.toBeNull();
  expect(
    screen.getByText(
      "Based on 3 similar completed jobs. Later steps and queue waits are separate.",
    ),
  ).not.toBeNull();
});

it("chooses the active workflow child instead of a succeeded preparation or queued parent", () => {
  const rows = [
    {
      id: "done",
      status: "succeeded",
      capability: "image.generate",
      generation_progress: measured,
    },
    {
      id: "queued",
      status: "queued",
      capability: "video.generate",
      generation_progress: { ...measured, phase: "queued" },
    },
    {
      id: "current",
      status: "running",
      capability: "video.generate",
      generation_progress: measured,
    },
  ] as Run[];
  render(<MediaRunProgress runs={rows} />);
  expect(screen.getAllByRole("progressbar")).toHaveLength(1);
  expect(
    screen
      .getByRole("progressbar", { name: "Video measured progress" })
      .getAttribute("value"),
  ).toBe("4");
});

it("does not retain a running progress card after a terminal result", () => {
  const { container } = render(
    <GenerationProgress progress={measured} status="succeeded" />,
  );
  expect(container.textContent).toBe("");
});

it("identifies prompt review rather than GPU waiting on a queued consumer", () => {
  render(
    <MediaRunProgress
      runs={[
        {
          ...basicRun,
          id: "review",
          status: "queued",
          capability: "image.generate",
          metadata: { prompt_translation: { status: "waiting_for_review" } },
          generation_progress: {
            ...measured,
            phase: "queued",
            estimate: null,
            fraction: null,
          },
        } as Run,
      ]}
    />,
  );
  expect(screen.getByText("Waiting for your review")).not.toBeNull();
  expect(screen.getByRole("progressbar").hasAttribute("value")).toBe(false);
});
