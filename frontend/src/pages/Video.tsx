import MediaJobResult from "../components/media/MediaJobResult";
import {
  useMediaJob,
  jobBusy,
  type MediaJob,
} from "../components/media/media-job";
import { chatRequestId, clearChatRequest } from "./chat-draft";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Film, Settings2, Sparkles } from "lucide-react";
import { api, useHardware, type Run } from "../api";
import { PageTitle, ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";
import MediaInput from "../components/media/MediaInput";
import MediaResult from "../components/media/MediaResult";
import { mediaBusy, useMediaRun } from "../components/media/media-run";
import { GpuTargetChoiceList } from "./GpuTargetChoiceList";
import Avatars from "./Avatars";

export default function Video() {
  const [search, setSearch] = useSearchParams();
  const currentRun = useMediaRun(search.get("run") ?? "");
  const currentJob = useMediaJob(search.get("job") ?? "");
  const busy = mediaBusy(currentRun.data) || jobBusy(currentJob.data);
  const avatar = search.get("mode") === "avatar" || !!search.get("audio");
  return (
    <>
      <nav className="mode-tabs" aria-label="Video type">
        <button
          type="button"
          disabled={busy}
          aria-pressed={!avatar}
          className={!avatar ? "active" : ""}
          onClick={() => setSearch(new URLSearchParams())}
        >
          Create a scene
        </button>
        <button
          type="button"
          disabled={busy}
          aria-pressed={avatar}
          className={avatar ? "active" : ""}
          onClick={() => setSearch({ mode: "avatar" })}
        >
          Talking avatar
        </button>
      </nav>
      {avatar ? (
        <Avatars video />
      ) : (
        <VideoForm
          key={search.get("input") ?? ""}
          initialImage={search.get("input") ?? ""}
        />
      )}
    </>
  );
}

function VideoForm({ initialImage }: { initialImage: string }) {
  const [search, setSearch] = useSearchParams();
  const cache = useQueryClient();
  const [mode, setMode] = useState(initialImage ? "animate" : "generate");
  const [image, setImage] = useState(initialImage);
  const [prompt, setPrompt] = useState("");
  const [negative, setNegative] = useState("");
  const [resolution, setResolution] = useState("1280x704");
  const [duration, setDuration] = useState("49");
  const [compositionMode, setCompositionMode] = useState<
    "continuous" | "shots"
  >("continuous");
  const [steps, setSteps] = useState(20);
  const [seed, setSeed] = useState(43);
  const [gpu, setGpu] = useState("auto");
  const [uploading, setUploading] = useState(false);
  const capability = useQuery({
    queryKey: ["video-capabilities"],
    queryFn: () =>
      api<{ available: boolean; reason?: string }>("/video/capabilities"),
  });
  const hardware = useHardware();
  const runId = search.get("run") ?? "";
  const run = useMediaRun(runId);
  const jobId = search.get("job") ?? "";
  const job = useMediaJob(jobId);
  const generate = useMutation({
    mutationFn: async () => {
      const [width, height] = resolution.split("x").map(Number);
      const values = {
        prompt,
        negative_prompt: negative,
        width,
        height,
        steps,
        seed,
        gpu,
        image_artifact_id: mode === "animate" ? image : null,
      };
      if (duration.endsWith("s")) {
        const body = {
          ...values,
          duration_seconds: Number(duration.slice(0, -1)),
          composition_mode: compositionMode,
        };
        const key = await chatRequestId("video-job", JSON.stringify(body));
        return api<MediaJob>("/media/jobs/video", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...body, client_request_id: key }),
        });
      }
      return api<Run>("/video/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt,
          negative_prompt: negative,
          width,
          height,
          frames: Number(duration),
          steps,
          seed,
          gpu,
          image_artifact_id: mode === "animate" ? image : null,
        }),
      });
    },
    onSuccess: (result) => {
      if ("revision" in result) {
        clearChatRequest("video-job");
        cache.setQueryData(["media-job", result.task_id], result);
        setSearch((current) => {
          const next = new URLSearchParams(current);
          next.delete("run");
          next.set("job", result.task_id);
          return next;
        });
        return;
      }
      cache.setQueryData(["run", result.id], result);
      setSearch((current) => {
        const next = new URLSearchParams(current);
        next.delete("job");
        next.set("run", result.id);
        return next;
      });
    },
  });
  const busy = generate.isPending || mediaBusy(run.data) || jobBusy(job.data);
  return (
    <>
      <PageTitle
        eyebrow="CREATE / VIDEO"
        title="Bring a scene to life."
        action={
          <span className="media-runtime">
            {capability.data?.available && <i />}
            Wan 2.2 · Local
          </span>
        }
      >
        Describe the motion, or start with an image. Create a silent video and
        preview it here.
      </PageTitle>
      <div className="media-workspace">
        <form
          className="panel media-composer"
          onSubmit={(event) => {
            event.preventDefault();
            if (
              !busy &&
              !uploading &&
              capability.data?.available &&
              prompt.trim() &&
              (mode !== "animate" || image)
            )
              generate.mutate();
          }}
        >
          <div className="media-composer-heading">
            <Film size={20} />
            <h2>Create video</h2>
            <span>01 / Scene & motion</span>
          </div>
          <fieldset disabled={busy || uploading}>
            <fieldset className="video-source-mode">
              <legend>Starting point</legend>
              <label>
                <input
                  type="radio"
                  name="video-source"
                  checked={mode === "generate"}
                  onChange={() => setMode("generate")}
                />
                Text to video
              </label>
              <label>
                <input
                  type="radio"
                  name="video-source"
                  checked={mode === "animate"}
                  onChange={() => setMode("animate")}
                />
                Animate an image
              </label>
            </fieldset>
            {mode === "animate" && (
              <MediaInput
                kind="image"
                label="First frame"
                hint="PNG or JPEG · up to 20 MB"
                value={image}
                onChange={setImage}
                disabled={busy || uploading}
                onBusy={setUploading}
              />
            )}
            <label className="media-text-label">
              <span>
                Scene and motion <small>{prompt.length} / 2000</small>
              </span>
              <textarea
                aria-label="Scene and motion"
                required
                maxLength={2000}
                rows={6}
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder="A cinematic shot of a forest at dawn. Mist drifts between the trees as the camera slowly moves forward…"
              />
            </label>
            <div className="video-output-options">
              <label>
                Format
                <select
                  value={resolution}
                  onChange={(event) => setResolution(event.target.value)}
                >
                  <option value="1280x704">Landscape · 1280 × 704</option>
                  <option value="704x1280">Portrait · 704 × 1280</option>
                  <option value="768x768">Square · 768 × 768</option>
                </select>
              </label>
              <label>
                Duration
                <select
                  value={duration}
                  onChange={(event) => setDuration(event.target.value)}
                >
                  <option value={33}>1.4 seconds</option>
                  <option value={49}>2 seconds</option>
                  <option value={81}>3.4 seconds</option>
                  <option value="15s">15 seconds</option>
                  <option value="30s">30 seconds</option>
                  <option value="60s">1 minute</option>
                </select>
              </label>
            </div>
            {duration.endsWith("s") && (
              <label>
                Composition
                <select
                  value={compositionMode}
                  onChange={(event) =>
                    setCompositionMode(
                      event.target.value as "continuous" | "shots",
                    )
                  }
                >
                  <option value="continuous">One continuous scene</option>
                  <option value="shots">Sequence of shots</option>
                </select>
                <small className="muted">
                  Long videos render in resumable segments, then become one
                  checked MP4.
                </small>
              </label>
            )}
            <details className="media-advanced">
              <summary>
                <Settings2 size={15} />
                Advanced settings<span>Steps, seed & GPU</span>
              </summary>
              <label>
                Negative prompt
                <textarea
                  maxLength={2000}
                  rows={2}
                  value={negative}
                  onChange={(event) => setNegative(event.target.value)}
                />
              </label>
              <div className="video-output-options">
                <label>
                  Steps
                  <input
                    type="number"
                    min={4}
                    max={40}
                    value={steps}
                    onChange={(event) => setSteps(Number(event.target.value))}
                  />
                </label>
                <label>
                  Seed
                  <input
                    type="number"
                    min={0}
                    max={2147483647}
                    value={seed}
                    onChange={(event) => setSeed(Number(event.target.value))}
                  />
                </label>
              </div>
              <GpuTargetChoiceList
                value={gpu}
                gpus={hardware.data?.gpus ?? []}
                disabled={busy || uploading}
                onChange={setGpu}
              />
            </details>
            <ErrorNotice error={generate.error ?? capability.error} />
            {capability.data && !capability.data.available && (
              <p className="notice">
                Local video needs setup. {capability.data.reason}{" "}
                <Link to="/system">Inspect system</Link>
              </p>
            )}
            <Button
              type="submit"
              className="media-generate"
              disabled={
                !capability.data?.available ||
                !prompt.trim() ||
                (mode === "animate" && !image) ||
                busy ||
                uploading
              }
            >
              <Sparkles size={17} />
              {busy ? "Creating your video…" : "Generate video"}
            </Button>
            <p className="media-privacy">
              Your images and prompt stay on this workstation. Output is 24 fps,
              without sound.
            </p>
          </fieldset>
        </form>
        {jobId ? (
          <MediaJobResult id={jobId} job={job.data} error={job.error} />
        ) : (
          <MediaResult
            kind="video"
            videoMode="scene"
            runId={runId}
            run={run.data}
            error={run.error}
          />
        )}
      </div>
    </>
  );
}
