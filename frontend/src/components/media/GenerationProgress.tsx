import { Clock3 } from "lucide-react";
import type { GenerationProgress as Observation, Run } from "../../api";
import "./GenerationProgress.css";

const terminal = new Set(["succeeded", "failed", "canceled", "interrupted"]);
const phases: Record<string, string> = {
  queued: "Waiting to start",
  claimed: "Preparing to start",
  preparing: "Preparing model and inputs",
  generating: "Generating on your workstation",
  finishing: "Decoding, saving and checking",
  waiting_for_approval: "Waiting for your review",
  cancel_requested: "Stopping generation…",
};
const labels: Record<string, string> = {
  "image.generate": "Image",
  "image.edit": "Image edit",
  "image.recompose": "Recompose",
  "image.upscale": "Upscale",
  "video.generate": "Video",
  "avatar.animate": "Avatar",
  "audio.speech": "Speech",
  "audio.music": "Music",
  "audio.effects": "Sound effects",
  "video.effects_preview": "Sound preview",
};
function duration(value: number) {
  const seconds = Math.max(1, Math.ceil(value));
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) {
    const remainder = seconds % 60;
    return `${Math.floor(seconds / 60)}m${remainder ? ` ${remainder}s` : ""}`;
  }
  const minutes = Math.ceil((seconds % 3600) / 60);
  return `${Math.floor(seconds / 3600)}h${minutes ? ` ${minutes}m` : ""}`;
}

export default function GenerationProgress({
  progress,
  status,
  label = "Generation",
}: {
  progress?: Observation | null;
  status: string;
  label?: string;
}) {
  if (!progress || terminal.has(status)) return null;
  const stopping = status === "cancel_requested";
  const fraction =
    !stopping && progress.phase === "generating" ? progress.fraction : null;
  const measured =
    fraction &&
    Number.isInteger(fraction.completed) &&
    Number.isInteger(fraction.total) &&
    fraction.total > 0 &&
    fraction.completed >= 0 &&
    fraction.completed <= fraction.total
      ? fraction
      : null;
  const estimate =
    stopping || ["queued", "waiting_for_approval"].includes(progress.phase)
      ? null
      : progress.estimate;
  const validEstimate =
    estimate &&
    Number.isFinite(estimate.upper_seconds) &&
    Number.isFinite(estimate.lower_seconds) &&
    estimate.upper_seconds > 0 &&
    estimate.lower_seconds >= 0 &&
    estimate.lower_seconds <= estimate.upper_seconds
      ? estimate
      : null;
  const phase = stopping
    ? phases.cancel_requested
    : (phases[progress.phase] ?? phases.generating);
  return (
    <section className="generation-progress" aria-label={`${label} progress`}>
      <div className="generation-progress-heading">
        <strong>{phase}</strong>
        {progress.elapsed_seconds > 0 && (
          <span>
            <Clock3 size={12} aria-hidden="true" />{" "}
            {duration(progress.elapsed_seconds)} elapsed
          </span>
        )}
      </div>
      <progress
        aria-label={`${label} measured progress`}
        aria-valuetext={
          measured
            ? `${measured.completed} of ${measured.total} ${measured.unit}`
            : phase
        }
        max={measured?.total ?? 100}
        value={measured?.completed}
      />
      {measured && (
        <p className="generation-progress-units">
          {measured.completed} of {measured.total} {measured.unit}
        </p>
      )}
      {validEstimate ? (
        <div
          className="generation-progress-estimate"
          aria-label="Estimated remaining time"
        >
          <p>
            <Clock3 size={13} aria-hidden="true" />{" "}
            {validEstimate.lower_seconds > 0
              ? `About ${duration(validEstimate.lower_seconds)} – ${duration(validEstimate.upper_seconds)}`
              : `Up to ${duration(validEstimate.upper_seconds)}`}{" "}
            {validEstimate.scope === "sampling"
              ? "of sampling left"
              : "for this step"}
          </p>
          <small>
            {validEstimate.scope === "sampling"
              ? "Measured from this generation. Saving and checks follow."
              : `Based on ${validEstimate.samples ?? 0} similar completed jobs. Later steps and queue waits are separate.`}
          </small>
        </div>
      ) : (
        !stopping && (
          <p className="generation-progress-learning">
            {progress.phase === "queued"
              ? "Time estimate starts after execution begins."
              : progress.phase === "finishing"
                ? "The result is still being saved and checked."
                : "A time estimate will appear when enough measurements are available."}
          </p>
        )
      )}
    </section>
  );
}

export function MediaRunProgress({ runs }: { runs: Run[] }) {
  const active = runs.filter(
    (run) => run.generation_progress && !terminal.has(run.status),
  );
  const executing = active.filter((run) => run.status !== "queued");
  const visible = (executing.length ? executing : active.slice(0, 1)).slice(
    0,
    6,
  );
  if (!visible.length) return null;
  return (
    <div className="generation-progress-list">
      {visible.map((run) => {
        const translation = run.metadata?.prompt_translation as
          { status?: string } | undefined;
        const review =
          run.status === "queued" &&
          translation?.status === "waiting_for_review";
        const progress =
          review && run.generation_progress
            ? { ...run.generation_progress, phase: "waiting_for_approval" }
            : run.generation_progress;
        return (
          <GenerationProgress
            key={run.id}
            progress={progress}
            status={review ? "waiting_for_approval" : run.status}
            label={labels[run.capability] ?? "Generation"}
          />
        );
      })}
    </div>
  );
}
