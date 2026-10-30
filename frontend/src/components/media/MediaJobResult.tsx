import { useMediaJob, jobBusy, type MediaJob } from "./media-job";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Film, Square, RotateCcw, ArrowUpRight, Download } from "lucide-react";
import { api, type Artifact } from "../../api";
import { Badge, ErrorNotice } from "../common";
import ResourceWaitNotice from "../ResourceWaitNotice";
import { Button } from "../ui/button";
import { chatRequestId, clearChatRequest } from "../../pages/chat-draft";
import PromptTranslation, {
  type TranslationRecovery,
} from "./PromptTranslation";
import { useMediaRun } from "./media-run";
import GenerationProgress from "./GenerationProgress";

function animationTime(seconds: number) {
  const minutes = Math.max(1, Math.ceil(seconds / 60));
  const hours = Math.floor(minutes / 60);
  return hours
    ? `${hours} h${minutes % 60 ? ` ${minutes % 60} min` : ""}`
    : `${minutes} min`;
}

function FilmPrompt({
  id,
  onRecover,
}: {
  id: string;
  onRecover: (action: TranslationRecovery) => Promise<unknown>;
}) {
  const run = useMediaRun(id);
  return run.data ? (
    <PromptTranslation run={run.data} onRecover={onRecover} />
  ) : (
    <ErrorNotice error={run.error} />
  );
}

export default function MediaJobResult({
  id,
  job: initialJob,
  error,
  allowResume = true,
  spokenText,
}: {
  id: string;
  job?: MediaJob;
  error?: Error | null;
  allowResume?: boolean;
  spokenText?: string;
}) {
  const cache = useQueryClient();
  const current = useMediaJob(id);
  const job = current.data ?? initialJob;
  const artifact = useQuery({
    queryKey: ["artifact", job?.final_artifact_id],
    queryFn: () => api<Artifact>(`/artifacts/${job!.final_artifact_id}`),
    enabled: !!job?.final_artifact_id,
  });
  const refresh = () =>
    cache.invalidateQueries({ queryKey: ["media-job", id] });
  const stop = useMutation({
    mutationFn: () => api(`/media/jobs/${id}/cancel`, { method: "POST" }),
    onSuccess: refresh,
  });
  const resume = useMutation({
    mutationFn: async (translation: TranslationRecovery = "reuse") => {
      if (translation !== "reuse" && jobBusy(job)) {
        try {
          await api(`/media/jobs/${id}/cancel`, { method: "POST" });
        } catch (error) {
          const actual = await api<MediaJob>(`/media/jobs/${id}`);
          if (
            actual.status !== "canceled" &&
            actual.status !== "cancel_requested"
          )
            throw error;
        }
        const deadline = Date.now() + 30000;
        while (true) {
          const actual = await api<MediaJob>(`/media/jobs/${id}`);
          if (!jobBusy(actual)) break;
          if (Date.now() >= deadline)
            throw new Error(
              "The film is still stopping. Inspect its Runs, then retry.",
            );
          await new Promise((resolve) => setTimeout(resolve, 500));
        }
      }
      const body = {
        expected_revision: job!.revision,
        ...(translation === "reuse" ? {} : { translation }),
      };
      const key = await chatRequestId(
        "media-resume:" + id,
        JSON.stringify(body),
      );
      return api<MediaJob>(`/media/jobs/${id}/resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...body, client_request_id: key }),
      });
    },
    onSuccess: (result) => {
      clearChatRequest("media-resume:" + id);
      cache.setQueryData(["media-job", id], result);
    },
  });
  const busy = jobBusy(job);
  const whole = job?.mode === "whole_recording";
  const native = job?.native_progress;
  const generationPercent =
    native && native.total_windows > 0
      ? Math.min(
          100,
          Math.floor((native.completed_windows * 100) / native.total_windows),
        )
      : null;
  const wholeProgressText =
    job?.status === "succeeded"
      ? "Your full video is ready."
      : job?.status === "cancel_requested"
        ? "Stopping the recording…"
        : job?.status === "canceled"
          ? "Recording stopped. Its execution history is saved."
          : job?.status === "failed"
            ? "The recording needs attention. Inspect the error below."
            : job?.resource_wait
              ? "Queued; generation will start when resources are available."
              : native?.phase === "finishing"
                ? "Saving and checking the complete recording…"
                : native?.phase === "animating"
                  ? `Animating the complete recording · ${generationPercent}%`
                  : job?.status === "preparing"
                    ? "Preparing speech for the complete recording…"
                    : "Preparing the local animation model…";
  const runningShots = job?.running_segments ?? 0;
  const activeShots = job?.active_segments ?? [];
  const shotSummary =
    job?.status === "cancel_requested"
      ? "Stopping active shots…"
      : runningShots > 0
        ? `${runningShots} ${runningShots === 1 ? "shot running" : "shots running"}`
        : activeShots.length
          ? "Preparing shots…"
          : "Waiting for available resources";
  return (
    <section className="panel media-job-result" aria-label="Media job">
      <div className="row spread">
        <h2>
          <Film size={20} />
          {job?.kind === "avatar" ? "Your talking avatar" : "Your film"}
        </h2>
        {job && <Badge status={job.status} />}
      </div>
      {job && (
        <>
          <p className="muted">
            {job.duration_seconds == null
              ? "Preparing the full speech"
              : `${job.duration_seconds.toLocaleString(undefined, { maximumFractionDigits: 2 })} seconds`}{" "}
            ·{" "}
            {whole
              ? "Whole-recording animation"
              : job.mode === "continuous"
                ? "Continuous motion"
                : "Sequence of shots"}{" "}
            · Local
            {whole &&
              job.result_geometry &&
              ` · ${job.result_geometry.width} × ${job.result_geometry.height} · ${job.result_geometry.fps} fps`}
          </p>
          {["queued", "preparing", "generating", "composing"].includes(
            job.status,
          ) && <ResourceWaitNotice wait={job.resource_wait} />}
          {busy &&
            job.active_generation_progress?.map((stage) => (
              <GenerationProgress
                key={stage.run_id}
                progress={stage}
                status={stage.status}
                label={`${job.kind === "avatar" ? "Avatar" : "Video"} step`}
              />
            ))}
          <div className="media-job-progress">
            <progress
              max={
                whole
                  ? (native?.total_windows ?? job.total_stages ?? 1)
                  : job.total_segments + 1
              }
              value={
                whole
                  ? job.status === "succeeded"
                    ? (native?.total_windows ?? job.total_stages ?? 1)
                    : busy && (!native || native.phase === "preparing")
                      ? undefined
                      : (native?.completed_windows ?? job.completed_stages ?? 0)
                  : job.status === "succeeded"
                    ? job.total_segments + 1
                    : job.completed_segments
              }
              aria-label={
                whole ? "Avatar animation progress" : "Completed video stages"
              }
            />
            <p>
              {whole
                ? wholeProgressText
                : job.prompt_preparation_status === "review"
                  ? "Review the translated prompts below before film generation."
                  : job.prompt_preparation_status === "translating"
                    ? "Preparing your film prompts locally…"
                    : job.status === "composing"
                      ? "Assembling and checking the full video…"
                      : job.resource_wait &&
                          (job.status === "queued" ||
                            job.status === "preparing")
                        ? "Queued; generation will start when resources are available."
                        : job.status === "preparing"
                          ? "Generating speech and preparing its full timeline…"
                          : job.status === "succeeded"
                            ? "Your full video is ready."
                            : `${job.completed_segments} of ${job.total_segments} ${job.mode === "shots" ? "shots" : "segments"} complete`}
            </p>
            {whole &&
              busy &&
              job.status === "generating" &&
              native?.phase === "animating" &&
              !job.resource_wait &&
              typeof job.estimated_animation_seconds === "number" &&
              job.estimated_animation_seconds > 0 && (
                <p className="muted" aria-label="Estimated animation time">
                  About {animationTime(job.estimated_animation_seconds)} of
                  animation left. Saving and checks follow.
                </p>
              )}
          </div>
          {job.kind === "video" &&
          job.mode === "shots" &&
          busy &&
          (job.active_segments?.length || (job.queued_segments ?? 0) > 0) ? (
            <section aria-label="Shot progress">
              <p className="muted">
                {shotSummary}
                {(job.queued_segments ?? 0) > 0 &&
                  ` · ${job.queued_segments} queued`}
              </p>
              {!!job.active_segments?.length && (
                <ul className="media-shot-list" aria-label="Active shots">
                  {job.active_segments.map((stage) => (
                    <li className="row" key={stage.run_id}>
                      <Link className="text-link" to={`/runs/${stage.run_id}`}>
                        Shot {stage.index + 1}
                      </Link>
                      {stage.gpu != null && (
                        <span className="muted">GPU {stage.gpu}</span>
                      )}
                      <Badge status={stage.status} />
                    </li>
                  ))}
                </ul>
              )}
            </section>
          ) : null}
          {!!job.scenes?.length && (
            <details className="media-scene-progress">
              <summary>
                {
                  job.scenes.filter((scene) => scene.status === "succeeded")
                    .length
                }{" "}
                of {job.scenes.length}{" "}
                {job.scenes.length === 1 ? "scene" : "scenes"} ready
              </summary>
              <ol aria-label="Scene progress">
                {job.scenes.map((scene) => (
                  <li key={scene.index}>
                    <div className="row spread">
                      <strong>
                        Scene {scene.index + 1} · {scene.duration_seconds}s
                      </strong>
                      <Badge status={scene.status} />
                    </div>
                    <p>{scene.prompt}</p>
                    <progress
                      aria-label={`Scene ${scene.index + 1} progress`}
                      max={scene.total_segments || 1}
                      value={scene.completed_segments}
                    />
                  </li>
                ))}
              </ol>
            </details>
          )}
          <div className="row">
            {busy && (
              <Button
                type="button"
                variant="secondary"
                disabled={stop.isPending || job.status === "cancel_requested"}
                onClick={() => stop.mutate()}
              >
                <Square size={15} />
                Stop film
              </Button>
            )}
            {allowResume && job.resume_allowed && (
              <Button
                type="button"
                variant="secondary"
                disabled={resume.isPending}
                onClick={() => resume.mutate("reuse")}
              >
                <RotateCcw size={15} />
                Resume unfinished work
              </Button>
            )}
            <Link to="/runs">Inspect Runs</Link>
          </div>
          {job.error_message && <p className="notice">{job.error_message}</p>}
          {job.translation_consumer_run_ids?.map((identifier) => (
            <FilmPrompt
              key={identifier}
              id={identifier}
              onRecover={(choice) => resume.mutateAsync(choice)}
            />
          ))}
        </>
      )}
      {job?.soundtrack_status &&
        !["succeeded", "failed"].includes(job.soundtrack_status) && (
          <p className="muted" role="status">
            {job.soundtrack_status === "waiting_for_film"
              ? "Sound will be created after the film."
              : job.soundtrack_status === "mixing"
                ? "Mixing the film and sound. The final movie will appear after verification."
                : "Creating the synchronized sound effects track."}
          </p>
        )}
      <ErrorNotice
        error={
          error ?? current.error ?? artifact.error ?? stop.error ?? resume.error
        }
      />
      {typeof spokenText === "string" && spokenText.trim() && (
        <section className="media-spoken-text" aria-label="Spoken text">
          <h3>Spoken text</h3>
          <p>{spokenText}</p>
        </section>
      )}
      {!job?.final_artifact_id && job?.preview_artifact_id && (
        <div className="media-partial-preview">
          <p className="muted">Latest completed segment · partial preview</p>
          <video
            controls
            preload="metadata"
            aria-label="Latest completed segment"
            src={`/api/artifacts/${job.preview_artifact_id}/file`}
          />
          <small className="muted">
            The full film is still being assembled. Finished segments are
            retained{allowResume ? " for Resume." : " in execution history."}
          </small>
        </div>
      )}
      {artifact.data && (
        <>
          <video
            controls
            preload="metadata"
            src={`/api/artifacts/${artifact.data.id}/file`}
            aria-label="Generated full video"
          />
          <div className="media-result-actions">
            <Button asChild variant="secondary">
              <Link to={`/library/${artifact.data.id}`}>
                <ArrowUpRight size={15} />
                Open in Library
              </Link>
            </Button>
            <Button asChild variant="secondary">
              <a href={`/api/artifacts/${artifact.data.id}/file`} download>
                <Download size={15} />
                Download MP4
              </a>
            </Button>
          </div>
        </>
      )}
    </section>
  );
}
