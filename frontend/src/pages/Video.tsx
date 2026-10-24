import MediaJobResult from "../components/media/MediaJobResult";
import {
  useMediaJob,
  jobBusy,
  type MediaJob,
  type MediaRequest,
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
import VideoSceneEditor from "../components/media/VideoSceneEditor";
import VideoMemoryProfile, {
  type VideoProfile,
  type VideoCapabilities,
} from "../components/media/VideoMemoryProfile";
import {
  scenePlanError,
  type SceneDraft,
} from "../components/media/video-scenes";

export default function Video() {
  const [search, setSearch] = useSearchParams();
  const currentRun = useMediaRun(search.get("run") ?? "");
  const currentJob = useMediaJob(search.get("job") ?? "");
  const busy =
    mediaBusy(currentRun.data) ||
    jobBusy(currentJob.data) ||
    (!!search.get("job") && currentJob.isPending);
  const avatar =
    search.get("mode") === "avatar" ||
    !!search.get("audio") ||
    currentJob.data?.kind === "avatar";
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
          key={`${search.get("input") ?? currentJob.data?.request?.image_artifact_id ?? ""}|${search.get("job") ?? ""}|${currentJob.data?.request ? "restored" : ""}`}
          initialImage={
            search.get("input") ??
            currentJob.data?.request?.image_artifact_id ??
            ""
          }
          initialRequest={currentJob.data?.request}
        />
      )}
    </>
  );
}

function VideoForm({
  initialImage,
  initialRequest,
}: {
  initialImage: string;
  initialRequest?: MediaRequest;
}) {
  const [search, setSearch] = useSearchParams();
  const cache = useQueryClient();
  const [mode, setMode] = useState(initialImage ? "animate" : "generate");
  const [image, setImage] = useState(initialImage);
  const [prompt, setPrompt] = useState(initialRequest?.prompt ?? "");
  const [negative, setNegative] = useState(
    initialRequest?.negative_prompt ?? "",
  );
  const [resolution, setResolution] = useState(
    initialRequest?.width && initialRequest?.height
      ? `${initialRequest.width}x${initialRequest.height}`
      : "1280x704",
  );
  const [duration, setDuration] = useState(
    initialRequest?.duration_seconds
      ? `${initialRequest.duration_seconds}s`
      : "49",
  );
  const [compositionMode, setCompositionMode] = useState<
    "continuous" | "shots"
  >(initialRequest?.composition_mode ?? "continuous");
  const [scenePlanning, setScenePlanning] = useState(
    !!initialRequest?.scenes?.length,
  );
  const [scenes, setScenes] = useState<SceneDraft[]>(
    () =>
      initialRequest?.scenes?.map((scene, index) => ({
        ...scene,
        key: `saved-${index}`,
      })) ?? [{ key: "first", prompt: "", duration_seconds: 5 }],
  );
  const planningScenes =
    duration.endsWith("s") && compositionMode === "shots" && scenePlanning;
  const totalSceneSeconds = scenes.reduce(
    (total, scene) => total + scene.duration_seconds,
    0,
  );
  const sceneError = planningScenes ? scenePlanError(prompt, scenes) : "";
  const [steps, setSteps] = useState(initialRequest?.steps ?? 20);
  const [profileChoice, setProfileChoice] = useState<VideoProfile | null>(
    initialRequest ? (initialRequest.memory_profile ?? "default") : null,
  );
  const [seed, setSeed] = useState(initialRequest?.seed ?? 43);
  const [gpu, setGpu] = useState(initialRequest?.gpu ?? "auto");
  const [uploading, setUploading] = useState(false);
  const capability = useQuery({
    queryKey: ["video-capabilities"],
    queryFn: () => api<VideoCapabilities>("/video/capabilities"),
  });
  const memoryProfile: VideoProfile =
    profileChoice ??
    (mode === "generate" &&
    resolution === "1280x704" &&
    steps >= 20 &&
    capability.data?.memory_profiles?.some(
      (row) => row.id === "bounded_11g" && row.available,
    ) &&
    capability.data.recommended_memory_profile === "bounded_11g"
      ? "bounded_11g"
      : "default");
  const hardware = useHardware();
  const runId = search.get("run") ?? "";
  const run = useMediaRun(runId);
  const jobId = search.get("job") ?? "";
  const job = useMediaJob(jobId);
  const generate = useMutation({
    mutationFn: async () => {
      const [width, height] = resolution.split("x").map(Number);
      const values = {
        ...(memoryProfile !== "default"
          ? { memory_profile: memoryProfile }
          : {}),
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
          duration_seconds: planningScenes
            ? totalSceneSeconds
            : Number(duration.slice(0, -1)),
          composition_mode: compositionMode,
          ...(planningScenes
            ? {
                scenes: scenes.map(({ prompt, duration_seconds }) => ({
                  prompt,
                  duration_seconds,
                })),
              }
            : {}),
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
          ...(memoryProfile !== "default"
            ? { memory_profile: memoryProfile }
            : {}),
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
  const busy =
    generate.isPending ||
    mediaBusy(run.data) ||
    jobBusy(job.data) ||
    (!!jobId && job.isPending);
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
              !sceneError &&
              prompt.trim() &&
              (mode !== "animate" || image)
            ) {
              setProfileChoice(memoryProfile);
              generate.mutate();
            }
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
                {planningScenes
                  ? "Shared style and setting"
                  : "Scene and motion"}{" "}
                <small>{prompt.length} / 2000</small>
              </span>
              <textarea
                aria-label={
                  planningScenes
                    ? "Shared style and setting"
                    : "Scene and motion"
                }
                required
                maxLength={2000}
                rows={planningScenes ? 3 : 6}
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder="A cinematic shot of a forest at dawn. Mist drifts between the trees as the camera slowly moves forward…"
              />
            </label>
            <div className="video-output-options">
              <label>
                Format
                <select
                  aria-label="Format"
                  value={resolution}
                  disabled={profileChoice === "bounded_11g"}
                  onChange={(event) => setResolution(event.target.value)}
                >
                  {!["1280x704", "704x1280", "768x768"].includes(
                    resolution,
                  ) && (
                    <option value={resolution}>
                      {resolution.replace("x", " × ")}
                    </option>
                  )}
                  <option value="1280x704">Landscape · 1280 × 704</option>
                  <option value="704x1280">Portrait · 704 × 1280</option>
                  <option value="768x768">Square · 768 × 768</option>
                </select>
              </label>
              <label>
                Duration
                {planningScenes ? (
                  <output
                    className="video-scene-total"
                    aria-label="Planned duration"
                  >
                    {totalSceneSeconds} seconds · planned
                  </output>
                ) : (
                  <select
                    aria-label="Duration"
                    value={duration}
                    onChange={(event) => setDuration(event.target.value)}
                  >
                    <option value={33}>1.4 seconds</option>
                    <option value={49}>2 seconds</option>
                    <option value={81}>3.4 seconds</option>
                    {duration.endsWith("s") &&
                      !["15s", "30s", "60s"].includes(duration) && (
                        <option value={duration}>
                          {duration.slice(0, -1)} seconds
                        </option>
                      )}
                    <option value="15s">15 seconds</option>
                    <option value="30s">30 seconds</option>
                    <option value="60s">1 minute</option>
                  </select>
                )}
              </label>
            </div>
            {duration.endsWith("s") && (
              <label>
                Composition
                <select
                  aria-label="Composition"
                  aria-describedby="video-composition-help"
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
                <small className="muted" id="video-composition-help">
                  Long videos render in resumable segments, then become one
                  checked MP4.
                </small>
              </label>
            )}
            {duration.endsWith("s") && compositionMode === "shots" && (
              <>
                <label className="video-scene-opt-in">
                  <input
                    type="checkbox"
                    checked={scenePlanning}
                    onChange={(event) => setScenePlanning(event.target.checked)}
                  />
                  Plan individual scenes
                </label>
                {planningScenes && (
                  <>
                    <VideoSceneEditor
                      scenes={scenes}
                      onChange={setScenes}
                      error={sceneError}
                    />
                    {jobId && !busy && (
                      <p className="muted">
                        Generate video creates a new film with these changes.
                        Resume unfinished work continues the saved plan.
                      </p>
                    )}
                  </>
                )}
              </>
            )}
            <details className="media-advanced">
              <summary>
                <Settings2 size={15} />
                Advanced settings<span>Steps, seed & GPU</span>
              </summary>
              <VideoMemoryProfile
                value={memoryProfile}
                recommended={profileChoice === null}
                onChange={(profile) => {
                  setProfileChoice(profile);
                  if (profile === "bounded_11g") {
                    setResolution("1280x704");
                    setSteps((current) => Math.max(20, current));
                  }
                }}
              />
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
                    min={profileChoice === "bounded_11g" ? 20 : 4}
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
                !!sceneError ||
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
