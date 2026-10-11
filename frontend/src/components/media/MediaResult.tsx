import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AudioLines,
  Film,
  Image as ImageIcon,
  LoaderCircle,
  ArrowUpRight,
  Square,
} from "lucide-react";
import { api, type Artifact, type Run } from "../../api";
import { Badge, ErrorNotice } from "../common";
import { Button } from "../ui/button";

import { mediaBusy } from "./media-run";
import { ArtifactLineage } from "../../pages/ArtifactLineage";

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
}: {
  kind: "audio" | "video" | "image";
  runId: string;
  run: Run | undefined;
  error: Error | null;
}) {
  const cache = useQueryClient();
  const artifacts = useQuery({
    queryKey: ["media-result", runId],
    queryFn: () => api<Artifact[]>(`/artifacts?run_id=${runId}`),
    enabled: !!runId && run?.status === "succeeded",
  });
  const cancel = useMutation({
    mutationFn: () => api(`/runs/${runId}/cancel`, { method: "POST" }),
    onSuccess: () => cache.invalidateQueries({ queryKey: ["run", runId] }),
  });
  const Icon =
    kind === "audio" ? AudioLines : kind === "video" ? Film : ImageIcon;
  const result = artifacts.data?.find((a) => a.type === kind);
  const busy = mediaBusy(run);
  const text = copy[kind];
  const statusText =
    run?.status === "queued"
      ? "Waiting for an available GPU"
      : run?.status === "cancel_requested"
        ? "Stopping generation…"
        : "Creating on your workstation";
  const file = result ? `/api/artifacts/${result.id}/file` : "";
  return (
    <aside className="panel media-result">
      <div className="media-result-heading">
        <div>
          <span className="eyebrow">OUTPUT</span>
          <h2>{text.title}</h2>
        </div>
        {run && <Badge status={run.status} />}
      </div>
      <ErrorNotice error={error ?? artifacts.error ?? cancel.error} />
      {result ? (
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
          <div className="media-result-actions">
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
            </div>
          )}
          {kind === "audio" && (
            <div className="media-result-reuse">
              <Button asChild variant="secondary">
                <Link
                  to={`/audio?input=${result.id}${runId ? `&run=${runId}` : ""}`}
                  aria-label={`Use as voice reference ${result.id.slice(0, 8)}`}
                >
                  Use as voice reference
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
          <div className="media-empty-icon">
            {busy ? (
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
          <p>
            {busy
              ? "You can stay here. Your result will appear automatically."
              : run
                ? run.error_message ||
                  "Inspect the run for details, then start a new generation."
                : text.idleBody}
          </p>
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
