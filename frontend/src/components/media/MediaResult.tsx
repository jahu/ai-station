import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AudioLines,
  Film,
  LoaderCircle,
  ArrowUpRight,
  Square,
} from "lucide-react";
import { api, type Artifact, type Run } from "../../api";
import { Badge, ErrorNotice } from "../common";
import { Button } from "../ui/button";

import { mediaBusy } from "./media-run";
import { ArtifactLineage } from "../../pages/ArtifactLineage";

export default function MediaResult({
  kind,
  runId,
  run,
  error,
}: {
  kind: "audio" | "video";
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
  const Icon = kind === "audio" ? AudioLines : Film;
  const result = artifacts.data?.find((a) => a.type === kind);
  const busy = mediaBusy(run);
  const statusText =
    run?.status === "queued"
      ? "Waiting for an available GPU"
      : run?.status === "cancel_requested"
        ? "Stopping generation…"
        : "Creating on your workstation";
  return (
    <aside className="panel media-result">
      <div className="media-result-heading">
        <div>
          <span className="eyebrow">OUTPUT</span>
          <h2>
            {kind === "audio"
              ? "Your voice, ready to play"
              : "Your portrait in motion"}
          </h2>
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
              src={`/api/artifacts/${result.id}/file`}
              aria-label="Generated video"
            />
          ) : (
            <div className="media-audio-output">
              <AudioLines size={50} />
              <audio
                controls
                preload="metadata"
                src={`/api/artifacts/${result.id}/file`}
                aria-label="Generated audio"
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
            <a href={`/api/artifacts/${result.id}/file`} download>
              Download {kind === "audio" ? "WAV" : "MP4"}
            </a>
          </div>
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
                  : kind === "audio"
                    ? "Turn your words into speech"
                    : "A portrait. A voice. A living moment."}
          </h3>
          <p>
            {busy
              ? "You can stay here. Your result will appear automatically."
              : run
                ? run.error_message ||
                  "Inspect the run for details, then start a new generation."
                : kind === "audio"
                  ? "Add a short voice reference and the words you want it to say."
                  : "Add a portrait and a speech recording. The finished video will appear here."}
          </p>
          {!run && (
            <div className="media-output-spec">
              <span>{kind === "audio" ? "WAV audio" : "MP4 video"}</span>
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
