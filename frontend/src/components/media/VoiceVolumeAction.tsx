import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { AudioLines, Check, LoaderCircle } from "lucide-react";
import { api, type Artifact, type Run } from "../../api";
import { randomId } from "../../lib/random-id";
import { Button } from "../ui/button";
import { ErrorNotice } from "../common";
import { useMediaRun, mediaBusy } from "./media-run";
import "./VoiceVolumeControl.css";

export default function VoiceVolumeAction({
  artifact,
}: {
  artifact: Artifact;
}) {
  const [requestId, setRequestId] = useState(randomId);
  const [runId, setRunId] = useState("");
  const cache = useQueryClient();
  const current = useMediaRun(runId);
  const mutation = useMutation({
    mutationFn: (key: string) =>
      api<Run>(`/artifacts/${artifact.id}/voice-level`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ client_request_id: key }),
      }),
    onSuccess: (run) => setRunId(run.id),
  });
  const stop = useMutation({
    mutationFn: () => api(`/runs/${runId}/cancel`, { method: "POST" }),
    onSuccess: () => cache.invalidateQueries({ queryKey: ["run", runId] }),
  });
  const done = current.data?.status === "succeeded";
  const resultId = current.data?.metadata?.result_artifact_id as
    string | undefined;
  const busy =
    mutation.isPending ||
    mediaBusy(current.data) ||
    (!!runId && current.isPending);
  const failed =
    !!current.data &&
    ["failed", "interrupted", "canceled"].includes(current.data.status);
  useEffect(() => {
    if (done)
      for (const key of [
        "library",
        "artifacts",
        "artifact-lineage",
        "media-inputs",
      ])
        void cache.invalidateQueries({ queryKey: [key] });
  }, [done, cache]);
  if (
    artifact.trashed_at ||
    artifact.purged_at ||
    artifact.purge_run_id ||
    !["audio/wav", "video/mp4"].includes(artifact.mime_type)
  )
    return null;
  const leveled =
    (artifact.metadata.audio_leveling as { profile?: string } | undefined)
      ?.profile === "speech-volume-v1";
  if (leveled)
    return (
      <div className="voice-level-action">
        <div>
          <Check size={16} /> Voice volume balanced
        </div>
      </div>
    );
  return (
    <section className="voice-level-action" aria-label="Voice volume">
      <div>
        {done && resultId ? (
          <Button asChild>
            <Link to={`/library/${resultId}`}>Open balanced copy</Link>
          </Button>
        ) : (
          <Button
            variant="secondary"
            disabled={busy || (!!runId && !failed)}
            onClick={() => {
              const next = failed ? randomId() : requestId;
              if (failed) {
                setRequestId(next);
                setRunId("");
              }
              mutation.mutate(next);
            }}
          >
            {busy ? (
              <LoaderCircle size={16} className="spin" />
            ) : (
              <AudioLines size={16} />
            )}
            {busy
              ? "Balancing voice…"
              : failed
                ? "Try voice leveling again"
                : "Even out voice volume"}
          </Button>
        )}
        {runId && <Link to={`/runs/${runId}`}>View task</Link>}
        {runId && busy && (
          <Button
            variant="ghost"
            disabled={stop.isPending}
            onClick={() => stop.mutate()}
          >
            Stop
          </Button>
        )}
      </div>
      <p>
        Create a separate copy with smoother speaking volume.{" "}
        {artifact.type === "video"
          ? "Video frames and lip sync stay intact."
          : "Words, pace and pauses stay intact."}{" "}
        The original is kept.
      </p>
      {busy && (
        <span role="status">
          Balancing speech. Your original stays available.
        </span>
      )}
      <ErrorNotice error={mutation.error ?? stop.error ?? current.error} />
      {current.data &&
        ["failed", "interrupted", "canceled"].includes(current.data.status) && (
          <p role="status">
            {current.data.error_message ||
              `Voice processing ${current.data.status}. Your original is unchanged.`}
          </p>
        )}
    </section>
  );
}
