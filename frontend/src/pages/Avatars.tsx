import {
  useCreative,
  useCreativeDraft,
  creativeRun,
  creativeJob,
} from "../components/creative/creative-context";
import MediaJobResult from "../components/media/MediaJobResult";
import {
  useMediaJob,
  jobBusy,
  type MediaJob,
  type MediaRequest,
} from "../components/media/media-job";
import { chatRequestId, clearChatRequest } from "./chat-draft";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { Film, Settings2, Sparkles, ArrowUpRight } from "lucide-react";
import { api, useHardware, type Run } from "../api";
import { ErrorNotice, PageTitle } from "../components/common";
import { Button } from "../components/ui/button";
import MediaInput from "../components/media/MediaInput";
import MediaResult from "../components/media/MediaResult";
import AvatarWholeProfile, {
  useWholeAvatarCapabilities,
  WHOLE_AVATAR_PROFILE,
} from "../components/media/AvatarWholeProfile";
import AvatarMemoryProfile, {
  useAvatarCapabilities,
  type AvatarProfile,
} from "../components/media/AvatarMemoryProfile";
import {
  mediaBusy,
  useMediaRun,
  useAvatarWorkflow,
} from "../components/media/media-run";
import { GpuTargetChoiceList } from "./GpuTargetChoiceList";
import {
  AvatarClipChoiceList,
  AvatarQualityChoiceList,
} from "./AvatarChoiceLists";

export default function Avatars({ video = false }: { video?: boolean }) {
  const [search] = useSearchParams();
  const creative = useCreative();
  const current = useMediaJob(search.get("job") ?? "");
  const saved = current.data?.request;
  // Remount when Library or a finished result chooses a portrait or speech,
  // not when a generation Run is recorded in the URL.
  return (
    <AvatarForm
      key={`${creative?.formKey ?? ""}|${search.get("image") ?? saved?.image_artifact_id ?? ""}|${search.get("audio") ?? saved?.audio_artifact_id ?? ""}|${search.get("job") ?? ""}|${saved ? "restored" : ""}`}
      video={video}
      initialImage={search.get("image") ?? saved?.image_artifact_id ?? null}
      initialAudio={search.get("audio") ?? saved?.audio_artifact_id ?? null}
      initialRequest={saved}
    />
  );
}

function AvatarForm({
  video,
  initialImage,
  initialAudio,
  initialRequest,
}: {
  video: boolean;
  initialImage: string | null;
  initialAudio: string | null;
  initialRequest?: MediaRequest;
}) {
  const creative = useCreative();
  const [initial] = useState(() => creative?.draft ?? {});
  const saved = (
    Object.keys(initial).length
      ? (initial.formState ?? initial)
      : (initialRequest ?? {})
  ) as Record<string, unknown>;
  const hasSavedSettings = Object.keys(saved).length > 0;
  const savedGeneration = saved.wholeRecording
    ? WHOLE_AVATAR_PROFILE
    : saved.generation_profile;
  const [search, setSearch] = useSearchParams();
  const cache = useQueryClient();
  const [image, setImage] = useState(
    String(saved.image ?? saved.image_artifact_id ?? initialImage ?? ""),
  );
  const [audio, setAudio] = useState(
    String(saved.audio ?? saved.audio_artifact_id ?? initialAudio ?? ""),
  );
  const [voiceMode, setVoiceMode] = useState<"recording" | "text">(
    saved.voiceMode === "text" || saved.speech_text ? "text" : "recording",
  );
  const [speechText, setSpeechText] = useState(
    String(saved.speechText ?? saved.speech_text ?? ""),
  );
  const [uploading, setUploading] = useState(false);
  const [prompt, setPrompt] = useState(
    String(saved.prompt ?? "A person speaking naturally, static camera."),
  );
  const [size, setSize] = useState(Number(saved.size ?? 384));
  const [frames, setFrames] = useState(Number(saved.frames ?? 81));
  const [fullRecording, setFullRecording] = useState(
    saved.fullRecording !== undefined
      ? Boolean(saved.fullRecording)
      : saved._creative_request_kind
        ? saved._creative_request_kind === "job"
        : true,
  );
  const [steps, setSteps] = useState(Number(saved.steps ?? 8));
  const [seed, setSeed] = useState(Number(saved.seed ?? 43));
  const [gpu, setGpu] = useState(String(saved.gpu ?? "auto"));
  const capability = useAvatarCapabilities();
  const whole = useWholeAvatarCapabilities();
  const savedLegacy = hasSavedSettings && !savedGeneration;
  const wholeRecording =
    fullRecording &&
    (!!savedGeneration ||
      (!savedLegacy &&
        (whole.isPending ||
          whole.isError ||
          whole.data?.available ||
          (whole.data?.readiness && whole.data.readiness !== "disabled"))));
  const checkingWhole =
    wholeRecording && (whole.isPending || whole.data?.readiness === "checking");
  const available = wholeRecording
    ? whole.data?.available === true && !whole.isError
    : capability.data?.available === true && !capability.isError;
  const [chosenProfile, setChosenProfile] = useState<AvatarProfile | null>(
    (saved.chosenProfile ??
      saved.memory_profile ??
      (initialRequest ? "default" : null)) as AvatarProfile | null,
  );
  const supportedProfile = size === 384 && steps >= 8;
  const memoryProfile =
    chosenProfile ??
    (supportedProfile
      ? (capability.data?.recommended_memory_profile ?? "default")
      : "default");
  const profileParameters =
    memoryProfile === "default" ? {} : { memory_profile: memoryProfile };
  useCreativeDraft({
    formState: {
      image,
      audio,
      voiceMode,
      speechText,
      prompt,
      size,
      frames,
      fullRecording,
      wholeRecording,
      steps,
      seed,
      gpu,
      chosenProfile: capability.data ? memoryProfile : chosenProfile,
    },
  });
  const hardware = useHardware();
  const runId = search.get("run") ?? "";
  const run = useMediaRun(runId);
  const jobId = search.get("job") ?? "";
  const job = useMediaJob(jobId);
  const workflow = useAvatarWorkflow(run.data);
  const activeRun = workflow.data?.steps.at(-1) ?? run.data;
  const generate = useMutation({
    mutationFn: async () => {
      if (fullRecording) {
        const body = {
          ...(wholeRecording
            ? { generation_profile: WHOLE_AVATAR_PROFILE }
            : { ...profileParameters, prompt, size, steps }),
          image_artifact_id: image,
          audio_artifact_id: audio,
          seed,
          gpu,
          ...(voiceMode === "text" ? { speech_text: speechText } : {}),
        };
        if (creative)
          return creativeJob(
            await creative.generate(body, {
              kind: "job",
              feedback: creative.draft._creative_parent_turn_id ? prompt : "",
            }),
          );
        const key = await chatRequestId("avatar-job", JSON.stringify(body));
        return api<MediaJob>("/media/jobs/avatar", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...body, client_request_id: key }),
        });
      }
      if (creative)
        return creativeRun(
          await creative.generate(
            {
              ...profileParameters,
              image_artifact_id: image,
              audio_artifact_id: audio,
              prompt,
              size,
              frames,
              steps,
              seed,
              gpu,
              ...(voiceMode === "text" ? { speech_text: speechText } : {}),
            },
            { feedback: creative.draft._creative_parent_turn_id ? prompt : "" },
          ),
        );
      return api<Run>("/avatars/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...profileParameters,
          image_artifact_id: image,
          audio_artifact_id: audio,
          prompt,
          size,
          frames,
          steps,
          seed,
          gpu,
          ...(voiceMode === "text" ? { speech_text: speechText } : {}),
        }),
      });
    },
    onSuccess: (result) => {
      if ("revision" in result) {
        clearChatRequest("avatar-job");
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
    mediaBusy(activeRun) ||
    jobBusy(job.data) ||
    (!!jobId && job.isPending) ||
    (!!run.data?.parameters?.avatar_after_speech && workflow.isPending);
  return (
    <>
      <PageTitle
        eyebrow={video ? "CREATE / VIDEO" : "CREATE / AVATARS"}
        title="Bring a portrait to life."
        action={
          <span className="media-runtime">
            {wholeRecording ? "Sonic" : "EchoMimic"} · Local
          </span>
        }
      >
        Combine a portrait with speech to create a talking avatar. Preview the
        finished film without leaving your workspace.
      </PageTitle>
      <div className="media-workspace">
        <form
          className="panel media-composer"
          onSubmit={(event) => {
            event.preventDefault();
            if (available && !busy && !uploading) generate.mutate();
          }}
        >
          <div className="media-composer-heading">
            <Film size={20} />
            <h2>Create avatar video</h2>
            <span>01 / Portrait & voice</span>
          </div>
          <fieldset disabled={busy || uploading}>
            <fieldset className="avatar-voice-mode video-source-mode">
              <legend>Speech source</legend>
              <label>
                <input
                  type="radio"
                  name="voice-mode"
                  value="recording"
                  checked={voiceMode === "recording"}
                  onChange={() => setVoiceMode("recording")}
                />
                Use a recording
              </label>
              <label>
                <input
                  type="radio"
                  name="voice-mode"
                  value="text"
                  checked={voiceMode === "text"}
                  onChange={() => setVoiceMode("text")}
                />
                Type what to say
              </label>
            </fieldset>
            <div className="media-source-grid">
              <MediaInput
                kind="image"
                label="Portrait"
                hint="PNG or JPG · up to 20 MB"
                value={image}
                onChange={setImage}
                disabled={busy || uploading}
                onBusy={setUploading}
              />
              <MediaInput
                kind="audio"
                label={
                  voiceMode === "text" ? "Voice reference" : "Speech recording"
                }
                hint={
                  voiceMode === "text"
                    ? "A short WAV sample of the voice to use"
                    : "WAV · 0.68–60 sec · up to 20 MB"
                }
                value={audio}
                onChange={setAudio}
                disabled={busy || uploading}
                onBusy={setUploading}
              />
            </div>
            {voiceMode === "text" && (
              <label className="media-text-label">
                <span>
                  Words to say <small>Local Polish speech</small>
                </span>
                <textarea
                  aria-label="Words to say"
                  required
                  maxLength={1000}
                  rows={3}
                  value={speechText}
                  onChange={(event) => setSpeechText(event.target.value)}
                  placeholder="Write a short sentence for your avatar…"
                />
                <small>
                  The voice sample sets the voice. AI Station generates these
                  words, then animates the portrait.
                </small>
              </label>
            )}
            <Link className="media-help-link" to="/audio">
              Need a voice recording? Create speech in Audio{" "}
              <ArrowUpRight size={13} />
            </Link>
            {wholeRecording && <AvatarWholeProfile checking={checkingWhole} />}
            {!wholeRecording && (
              <label className="media-text-label">
                <span>
                  Scene & motion <small>Optional direction</small>
                </span>
                <textarea
                  aria-label="Scene and motion"
                  required
                  maxLength={2000}
                  rows={3}
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                  placeholder="Describe the expression, motion or camera…"
                />
              </label>
            )}
            <div className="media-field-pair">
              {!wholeRecording && (
                <div>
                  <span>Quality</span>
                  <AvatarQualityChoiceList
                    value={size}
                    disabled={busy || uploading}
                    onChange={setSize}
                  />
                </div>
              )}
              <div>
                <span>Length</span>
                <label className="work-context-consent">
                  <input
                    type="checkbox"
                    checked={fullRecording}
                    disabled={busy || uploading}
                    onChange={(event) => setFullRecording(event.target.checked)}
                  />
                  Full recording (up to 60 seconds)
                </label>
                {!fullRecording && (
                  <AvatarClipChoiceList
                    value={frames}
                    disabled={busy || uploading}
                    onChange={setFrames}
                  />
                )}
              </div>
            </div>
            <details className="media-advanced">
              <summary>
                <Settings2 size={15} />
                Advanced settings
                <span>{wholeRecording ? "Seed, GPU" : "Steps, seed, GPU"}</span>
              </summary>
              {!wholeRecording && (
                <AvatarMemoryProfile
                  value={memoryProfile}
                  onChange={setChosenProfile}
                  disabled={busy || uploading}
                  supported={supportedProfile}
                  recommended={chosenProfile === null}
                />
              )}
              <div className="media-field-pair">
                {!wholeRecording && (
                  <label>
                    Steps
                    <input
                      type="number"
                      min={4}
                      max={30}
                      value={steps}
                      onChange={(event) => setSteps(Number(event.target.value))}
                    />
                  </label>
                )}
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
              <div>
                <span>GPU</span>
                <GpuTargetChoiceList
                  value={gpu}
                  gpus={hardware.data?.gpus ?? []}
                  disabled={uploading || busy}
                  onChange={setGpu}
                />
              </div>
              <ErrorNotice error={hardware.error} />
              {wholeRecording && (
                <small className="muted">
                  Auto uses up to two available GPUs. Select one GPU to leave
                  the other free.
                </small>
              )}
            </details>
            <ErrorNotice
              error={
                generate.error ??
                (wholeRecording ? whole.error : capability.error)
              }
            />
            {!wholeRecording && capability.isPending && (
              <p className="media-privacy" role="status">
                Checking local avatar runtime…
              </p>
            )}
            {!wholeRecording &&
              capability.data &&
              !capability.data.available && (
                <p className="notice" role="status">
                  Local avatar generation needs setup. {capability.data.reason}{" "}
                  <Link to="/system">Inspect system</Link>
                </p>
              )}
            {wholeRecording &&
              !checkingWhole &&
              whole.data &&
              !whole.data.available && (
                <p className="notice" role="status">
                  High-detail avatar generation needs setup.{" "}
                  <Link to="/system">Inspect system</Link>
                </p>
              )}
            <Button
              type="submit"
              className="media-generate"
              disabled={
                !available ||
                !image ||
                !audio ||
                (!wholeRecording && !prompt.trim()) ||
                (!wholeRecording &&
                  memoryProfile === "bounded_11g" &&
                  !supportedProfile) ||
                (voiceMode === "text" && !speechText.trim()) ||
                uploading ||
                busy
              }
            >
              <Sparkles size={17} />
              {busy ? "Creating your avatar…" : "Generate avatar video"}
            </Button>
            <p className="media-privacy">
              {fullRecording
                ? "Uses the whole recording or generated speech · preserves portrait proportions."
                : "Short preview · animates only the start of the recording."}
            </p>
          </fieldset>
        </form>
        {!creative &&
          (jobId ? (
            <MediaJobResult id={jobId} job={job.data} error={job.error} />
          ) : (
            <MediaResult
              kind="video"
              runId={activeRun?.id ?? runId}
              run={activeRun}
              steps={workflow.data?.steps}
              error={run.error ?? workflow.error}
            />
          ))}
      </div>
    </>
  );
}
