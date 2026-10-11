import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { Film, Settings2, Sparkles, ArrowUpRight } from "lucide-react";
import { api, useHardware, type Run } from "../api";
import { ErrorNotice, PageTitle } from "../components/common";
import { Button } from "../components/ui/button";
import MediaInput from "../components/media/MediaInput";
import MediaResult from "../components/media/MediaResult";
import { mediaBusy, useMediaRun } from "../components/media/media-run";
import { GpuTargetChoiceList } from "./GpuTargetChoiceList";
import {
  AvatarClipChoiceList,
  AvatarQualityChoiceList,
} from "./AvatarChoiceLists";

export default function Avatars({ video = false }: { video?: boolean }) {
  const [search] = useSearchParams();
  // Remount when Library or a finished result chooses a portrait or speech,
  // not when a generation Run is recorded in the URL.
  return (
    <AvatarForm
      key={`${search.get("image") ?? ""}|${search.get("audio") ?? ""}`}
      video={video}
      initialImage={search.get("image")}
      initialAudio={search.get("audio")}
    />
  );
}

function AvatarForm({
  video,
  initialImage,
  initialAudio,
}: {
  video: boolean;
  initialImage: string | null;
  initialAudio: string | null;
}) {
  const [search, setSearch] = useSearchParams();
  const cache = useQueryClient();
  const [image, setImage] = useState(initialImage ?? "");
  const [audio, setAudio] = useState(initialAudio ?? "");
  const [uploading, setUploading] = useState(false);
  const [prompt, setPrompt] = useState(
    "A person speaking naturally, static camera.",
  );
  const [size, setSize] = useState(384);
  const [frames, setFrames] = useState(81);
  const [steps, setSteps] = useState(8);
  const [seed, setSeed] = useState(43);
  const [gpu, setGpu] = useState("auto");
  const hardware = useHardware();
  const runId = search.get("run") ?? "";
  const run = useMediaRun(runId);
  const generate = useMutation({
    mutationFn: () =>
      api<Run>("/avatars/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          image_artifact_id: image,
          audio_artifact_id: audio,
          prompt,
          size,
          frames,
          steps,
          seed,
          gpu,
        }),
      }),
    onSuccess: (result) => {
      cache.setQueryData(["run", result.id], result);
      setSearch((current) => {
        const next = new URLSearchParams(current);
        next.set("run", result.id);
        return next;
      });
    },
  });
  const busy = generate.isPending || mediaBusy(run.data);
  return (
    <>
      <PageTitle
        eyebrow={video ? "CREATE / VIDEO" : "CREATE / AVATARS"}
        title="Bring a portrait to life."
        action={
          <span className="media-runtime">
            <i />
            EchoMimic · Local
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
            if (!busy && !uploading) generate.mutate();
          }}
        >
          <div className="media-composer-heading">
            <Film size={20} />
            <h2>Create avatar video</h2>
            <span>01 / Portrait & voice</span>
          </div>
          <fieldset disabled={busy || uploading}>
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
                label="Speech recording"
                hint="WAV · 0.68–60 sec · up to 20 MB"
                value={audio}
                onChange={setAudio}
                disabled={busy || uploading}
                onBusy={setUploading}
              />
            </div>
            <Link className="media-help-link" to="/audio">
              Need a voice recording? Create speech in Audio{" "}
              <ArrowUpRight size={13} />
            </Link>
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
            <div className="media-field-pair">
              <div>
                <span>Quality</span>
                <AvatarQualityChoiceList
                  value={size}
                  disabled={busy || uploading}
                  onChange={setSize}
                />
              </div>
              <div>
                <span>Clip length</span>
                <AvatarClipChoiceList
                  value={frames}
                  disabled={busy || uploading}
                  onChange={setFrames}
                />
              </div>
            </div>
            <details className="media-advanced">
              <summary>
                <Settings2 size={15} />
                Advanced settings<span>Steps, seed, GPU</span>
              </summary>
              <div className="media-field-pair">
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
            </details>
            <ErrorNotice error={generate.error} />
            <Button
              type="submit"
              className="media-generate"
              disabled={!image || !audio || !prompt.trim() || uploading || busy}
            >
              <Sparkles size={17} />
              {busy ? "Creating your avatar…" : "Generate avatar video"}
            </Button>
            <p className="media-privacy">
              Uses the start of your recording · preserves portrait proportions.
            </p>
          </fieldset>
        </form>
        <MediaResult
          kind="video"
          runId={runId}
          run={run.data}
          error={run.error}
        />
      </div>
    </>
  );
}
