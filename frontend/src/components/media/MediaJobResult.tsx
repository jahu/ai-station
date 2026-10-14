import { useMediaJob, jobBusy, type MediaJob } from "./media-job";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Film, Square, RotateCcw } from "lucide-react";
import { api, type Artifact } from "../../api";
import { Badge, ErrorNotice } from "../common";
import { Button } from "../ui/button";
import { chatRequestId, clearChatRequest } from "../../pages/chat-draft";

export default function MediaJobResult({
  id,
  job: initialJob,
  error,
}: {
  id: string;
  job?: MediaJob;
  error?: Error | null;
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
    mutationFn: async () => {
      const body = { expected_revision: job!.revision };
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
              : `${job.duration_seconds} seconds`}{" "}
            ·{" "}
            {job.mode === "continuous"
              ? "Continuous motion"
              : "Sequence of shots"}{" "}
            · Local
          </p>
          <div className="media-job-progress">
            <progress
              max={job.total_segments + 1}
              value={
                job.status === "succeeded"
                  ? job.total_segments + 1
                  : job.completed_segments
              }
              aria-label="Completed video stages"
            />
            <p>
              {job.status === "composing"
                ? "Assembling and checking the full video…"
                : job.status === "preparing"
                  ? "Generating speech and preparing its full timeline…"
                  : job.status === "succeeded"
                    ? "Your full video is ready."
                    : `${job.completed_segments} of ${job.total_segments} segments complete`}
            </p>
          </div>
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
            {job.resume_allowed && (
              <Button
                type="button"
                variant="secondary"
                disabled={resume.isPending}
                onClick={() => resume.mutate()}
              >
                <RotateCcw size={15} />
                Resume unfinished work
              </Button>
            )}
            <Link to="/runs">Inspect Runs</Link>
          </div>
          {job.error_message && <p className="notice">{job.error_message}</p>}
        </>
      )}
      <ErrorNotice
        error={
          error ?? current.error ?? artifact.error ?? stop.error ?? resume.error
        }
      />
      {artifact.data && (
        <>
          <video
            controls
            preload="metadata"
            src={`/api/artifacts/${artifact.data.id}/file`}
            aria-label="Generated full video"
          />
          <div className="row">
            <a href={`/api/artifacts/${artifact.data.id}/file`} download>
              Download MP4
            </a>
            <Link to={`/library/${artifact.data.id}`}>Open in Library</Link>
          </div>
        </>
      )}
    </section>
  );
}
