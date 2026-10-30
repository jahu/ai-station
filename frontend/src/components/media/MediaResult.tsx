import ImageModelSelection from "./ImageModelSelection";
import SpeechModelSelection from "./SpeechModelSelection";
import AddSoundLink from "./AddSoundLink";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AudioLines,
  Film,
  Image as ImageIcon,
  LoaderCircle,
  ArrowUpRight,
  Square,
  FileText,
} from "lucide-react";
import { api, type Artifact, type Run } from "../../api";
import { Badge, ErrorNotice } from "../common";
import ResourceWaitNotice from "../ResourceWaitNotice";
import { Button } from "../ui/button";

import { mediaBusy, useMediaRun } from "./media-run";
import { ArtifactLineage } from "../../pages/ArtifactLineage";
import LibraryActions from "../../pages/LibraryActions";
import { PurgeActivity } from "../../pages/LibraryPurge";
import PromptTranslation from "./PromptTranslation";
import { MediaRunProgress } from "./GenerationProgress";

const RETRYABLE = new Set(["failed", "canceled", "interrupted"]);

const copy = {
  audio: {
    title: "Your voice, ready to play",
    idleTitle: "Turn your words into speech",
    idleBody: "Add a short voice reference and the words you want it to say.",
    spec: "WAV audio",
    download: "WAV",
    label: "Generated audio",
  },
  video: {
    title: "Your portrait in motion",
    idleTitle: "A portrait. A voice. A living moment.",
    idleBody:
      "Add a portrait and a speech recording. The finished video will appear here.",
    spec: "MP4 video",
    download: "MP4",
    label: "Generated video",
  },
  image: {
    title: "Your image, ready to inspect",
    idleTitle: "Make the picture here",
    idleBody:
      "Describe a scene or attach a source. The finished image will appear here.",
    spec: "Image artifact",
    download: "image",
    label: "Generated image",
  },
} as const;

export default function MediaResult({
  kind,
  runId,
  run,
  error,
  steps,
  videoMode = "avatar",
  audioMode = "speech",
  allowRetry = true,
}: {
  kind: "audio" | "video" | "image";
  runId: string;
  run: Run | undefined;
  error: Error | null;
  steps?: Run[];
  videoMode?: "scene" | "avatar";
  audioMode?: "speech" | "music" | "effects";
  allowRetry?: boolean;
}) {
  const cache = useQueryClient();
  const preparationId = run?.parameters?.reference_transcription_run_id;
  const preparation = useMediaRun(
    run?.parameters?.backend === "fish_s2_pro" &&
      typeof preparationId === "string"
      ? preparationId
      : "",
  );
  const [, setSearch] = useSearchParams();
  const artifacts = useQuery({
    queryKey: ["media-result", runId],
    queryFn: () => api<Artifact[]>(`/artifacts?run_id=${runId}`),
    enabled: !!runId && run?.status === "succeeded",
  });
  const cancel = useMutation({
    mutationFn: () => api(`/runs/${runId}/cancel`, { method: "POST" }),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["run", runId] });
      void cache.invalidateQueries({ queryKey: ["image-workflow"] });
      return cache.invalidateQueries({ queryKey: ["avatar-workflow"] });
    },
  });
  const retry = useMutation({
    mutationFn: () =>
      api<Run>(`/images/runs/${runId}/retry`, { method: "POST" }),
    onSuccess: (next) => {
      cache.setQueryData(["run", next.id], next);
      void cache.invalidateQueries({ queryKey: ["runs"] });
      setSearch((current) => {
        const params = new URLSearchParams(current);
        params.set("run", next.id);
        return params;
      });
    },
  });
  const canRetry =
    allowRetry &&
    kind === "image" &&
    !!run &&
    RETRYABLE.has(run.status) &&
    (!run.metadata?.prompt_translation ||
      ["ready", "original"].includes(
        (run.metadata.prompt_translation as { status: string }).status,
      ));
  const Icon =
    kind === "audio" ? AudioLines : kind === "video" ? Film : ImageIcon;
  const result = artifacts.data?.find((a) => a.type === kind);
  const busy = mediaBusy(run);
  const progressRuns = steps ?? (run ? [run] : []);
  const measuredProgress =
    busy && progressRuns.some((step) => step.generation_progress);
  const text =
    kind === "video" && videoMode === "scene"
      ? {
          ...copy.video,
          title: "Your scene in motion",
          label: "Generated scene video",
          idleTitle: "Imagine it. Watch it move.",
          idleBody:
            "Describe a scene or choose a first frame. Your video will appear here.",
        }
      : kind === "audio" && audioMode === "effects"
        ? {
            ...copy.audio,
            title: "Your effects track",
            label: "Generated sound effects",
            idleTitle: "Let your film be heard",
            idleBody:
              "Choose a film and describe its sounds. Your effects and video preview will appear here.",
          }
        : kind === "audio" && audioMode === "music"
          ? {
              ...copy.audio,
              title: "Your music, ready to play",
              label: "Generated music",
              idleTitle: "Set the mood. Find your sound.",
              idleBody:
                "Describe a style, instruments and atmosphere. Your music will appear here.",
            }
          : copy[kind];
  const translation = run?.metadata?.prompt_translation as
    { status: string } | undefined;
  const waitingPromptReview =
    translation?.status === "waiting_for_review" && run?.status === "queued";
  const statusText =
    translation &&
    !["ready", "original"].includes(translation.status) &&
    run?.status === "queued"
      ? translation.status === "waiting_for_review"
        ? "Review your translated prompt"
        : "Preparing your prompt locally"
      : run?.status === "queued"
        ? run.resource_wait
          ? "Queued; generation has not started"
          : kind === "audio" && audioMode === "music"
            ? "Waiting for an available GPU and enough memory"
            : "Waiting for an available GPU"
        : run?.status === "cancel_requested"
          ? "Stopping generation…"
          : "Creating on your workstation";
  const file = result ? `/api/artifacts/${result.id}/file` : "";
  const spokenText =
    kind === "audio" &&
    audioMode === "speech" &&
    (run?.capability === "audio.speech" ||
      run?.executor_type === "chatterbox") &&
    typeof run?.parameters.text === "string"
      ? run.parameters.text
      : null;
  return (
    <aside className="panel media-result">
      <div className="media-result-heading">
        <div>
          <span className="eyebrow">OUTPUT</span>
          <h2>{text.title}</h2>
        </div>
        {run && <Badge status={run.status} />}
      </div>
      <ImageModelSelection run={run} />
      <SpeechModelSelection run={run} preparation={preparation.data} />
      <ErrorNotice
        error={error ?? artifacts.error ?? cancel.error ?? retry.error}
      />
      {run?.status === "queued" && (
        <ResourceWaitNotice wait={run.resource_wait} />
      )}
      {!!run?.metadata?.prompt_translation && (
        <PromptTranslation key={run.id} run={run} />
      )}
      {steps && (
        <ol
          aria-label={
            kind === "video" && videoMode === "avatar"
              ? "Avatar workflow"
              : "Image workflow"
          }
          className="media-workflow"
        >
          {steps.map((step, index) => (
            <li key={step.id}>
              <Link to={`/runs/${step.id}`}>
                {index + 1}.{" "}
                {step.capability === "image.upscale"
                  ? "Upscale 4×"
                  : step.capability === "image.edit"
                    ? "Edit"
                    : step.capability === "image.recompose"
                      ? "Recompose"
                      : step.capability === "audio.speech"
                        ? "Speech"
                        : step.capability === "video.generate"
                          ? "Animate scene"
                          : step.capability === "avatar.animate"
                            ? "Animate portrait"
                            : "Generate"}
              </Link>
              <Badge status={step.status} />
            </li>
          ))}
        </ol>
      )}
      {result && <PurgeActivity artifactId={result.id} />}
      {result?.purged_at || result?.purge_run_id ? (
        <div className="media-finished library-deleted-placeholder">
          <Icon size={40} />
          <h3>
            {result.purged_at
              ? "Result permanently deleted"
              : "Permanent deletion started"}
          </h3>
          <p>
            Generation history is preserved. This file can no longer be
            downloaded or reused.
          </p>
          <Link to={`/library/${result.id}`}>Inspect preserved history</Link>
          <ArtifactLineage artifactId={result.id} />
        </div>
      ) : result ? (
        <div className="media-finished">
          {kind === "video" ? (
            <video
              controls
              preload="metadata"
              src={file}
              aria-label={text.label}
            />
          ) : kind === "image" ? (
            <a href={file} target="_blank" rel="noreferrer">
              <img src={file} alt={text.label} />
            </a>
          ) : (
            <div className="media-audio-output">
              <AudioLines size={50} />
              <audio
                controls
                preload="metadata"
                src={file}
                aria-label={text.label}
              />
            </div>
          )}
          <p className="media-result-title">
            {result.title || result.original_filename}
          </p>
          {spokenText?.trim() && (
            <section className="media-spoken-text" aria-label="Spoken text">
              <h3>Spoken text</h3>
              <p>{spokenText}</p>
            </section>
          )}
          {kind === "audio" &&
            audioMode === "music" &&
            typeof run?.parameters.lyrics === "string" &&
            run.parameters.lyrics.trim() && (
              <section className="media-spoken-text" aria-label="Song lyrics">
                <h3>Song lyrics</h3>
                <p>{run.parameters.lyrics}</p>
              </section>
            )}
          <div className="media-result-actions">
            <AddSoundLink artifact={result} />
            <Button asChild variant="secondary">
              <Link to={`/library/${result.id}`}>
                <ArrowUpRight size={15} />
                Open in Library
              </Link>
            </Button>
            <a href={file} download>
              Download {text.download}
            </a>
          </div>
          <LibraryActions artifact={result} />
          {kind === "image" && (
            <div className="media-result-reuse">
              {(
                [
                  ["img2img", "Edit"],
                  ["recompose", "Recompose"],
                  ["upscale", "Upscale"],
                ] as const
              ).map(([mode, label]) => (
                <Button key={mode} asChild variant="secondary">
                  <Link
                    to={`/images?mode=${mode}&input=${result.id}${runId ? `&run=${runId}` : ""}`}
                    aria-label={`${label} ${result.id.slice(0, 8)}`}
                  >
                    {label}
                  </Link>
                </Button>
              ))}
              <Button asChild variant="secondary">
                <Link
                  to={`/avatars?image=${result.id}`}
                  aria-label={`Use as portrait ${result.id.slice(0, 8)}`}
                >
                  Use as portrait
                </Link>
              </Button>
            </div>
          )}
          {kind === "audio" && audioMode === "speech" && (
            <div className="media-result-reuse">
              <Button asChild variant="secondary">
                <Link
                  to={`/audio?input=${result.id}${runId ? `&run=${runId}` : ""}`}
                  aria-label={`Use as voice reference ${result.id.slice(0, 8)}`}
                >
                  Use as voice reference
                </Link>
              </Button>
              <Button asChild variant="secondary">
                <Link
                  to={`/avatars?audio=${result.id}`}
                  aria-label={`Use as speech ${result.id.slice(0, 8)}`}
                >
                  Use as speech
                </Link>
              </Button>
            </div>
          )}
          <ArtifactLineage artifactId={result.id} />
        </div>
      ) : (
        <div
          className={`media-empty ${busy ? "is-working" : ""}`}
          aria-live="polite"
        >
          {measuredProgress ? (
            <MediaRunProgress runs={progressRuns} />
          ) : (
            <>
              <div className="media-empty-icon">
                {waitingPromptReview ? (
                  <FileText size={32} />
                ) : busy ? (
                  <LoaderCircle size={32} className="media-spinner" />
                ) : (
                  <Icon size={36} />
                )}
              </div>
              <h3>
                {busy
                  ? statusText
                  : run && run.status !== "succeeded"
                    ? "Generation did not complete"
                    : run
                      ? "Loading your result…"
                      : text.idleTitle}
              </h3>
            </>
          )}
          <p>
            {waitingPromptReview
              ? "Confirm the prepared prompt above to start generation."
              : busy
                ? "You can stay here. Your result will appear automatically."
                : run
                  ? run.error_message ||
                    "Inspect the run for details, then start a new generation."
                  : text.idleBody}
          </p>
          {canRetry && (
            <div className="media-result-retry">
              <p className="muted">
                A retry creates a new run with the same parameters and source
                images. Inspect logs and any partial output before repeating an
                interrupted run.
              </p>
              <Button
                type="button"
                variant="secondary"
                disabled={retry.isPending}
                aria-label={`Retry as a new run ${runId.slice(0, 8)}`}
                onClick={() => retry.mutate()}
              >
                {retry.isPending ? "Retrying…" : "Retry as a new run"}
              </Button>
            </div>
          )}
          {!run && (
            <div className="media-output-spec">
              <span>{text.spec}</span>
              <span>Saved to Library</span>
              <span>Local execution</span>
            </div>
          )}
        </div>
      )}
      {runId && (
        <footer className="media-result-footer">
          <Link to={`/runs/${runId}`}>
            View run & logs <ArrowUpRight size={13} />
          </Link>
          {busy && (
            <Button
              type="button"
              variant="ghost"
              disabled={cancel.isPending || run?.status === "cancel_requested"}
              onClick={() => cancel.mutate()}
            >
              <Square size={12} />
              Stop generation
            </Button>
          )}
        </footer>
      )}
    </aside>
  );
}
