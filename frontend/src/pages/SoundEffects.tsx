import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { Waves, Settings2, Sparkles } from "lucide-react";
import { api, useHardware, type Run, type Artifact } from "../api";
import { ErrorNotice, PageTitle } from "../components/common";
import { Button } from "../components/ui/button";
import MediaInput from "../components/media/MediaInput";
import MediaResult from "../components/media/MediaResult";
import { mediaBusy, useMediaRun } from "../components/media/media-run";
import {
  useCreative,
  useCreativeDraft,
  creativeRun,
} from "../components/creative/creative-context";
import {
  PromptTranslationControl,
  translationRequest,
  type TranslationOptions,
} from "../components/media/PromptTranslation";
import { GpuTargetChoiceList } from "./GpuTargetChoiceList";
import SoundCueEditor from "../components/media/SoundCueEditor";
import { cuesValid, type SoundCue } from "../components/media/sound-cues";
import "./SoundEffects.css";

type Ready = {
  available: boolean;
  readiness: string;
  reason?: string;
  configuration_source?: "managed" | "configured";
  eligible_gpu_indices?: number[];
};
export default function SoundEffects() {
  const creative = useCreative();
  const [search, setSearch] = useSearchParams();
  const cache = useQueryClient();
  const [initial] = useState(() => creative?.draft ?? {});
  const restored = (initial.formState ?? initial) as Record<string, unknown>;
  const [video, setVideo] = useState(
    String(restored.video_artifact_id ?? search.get("input") ?? ""),
  );
  const [prompt, setPrompt] = useState(String(restored.prompt ?? ""));
  const [cues, setCues] = useState<SoundCue[]>(
    Array.isArray(restored.cues) ? restored.cues : [],
  );
  const source = useQuery({
    queryKey: ["artifact", video],
    queryFn: () => api<Artifact>(`/artifacts/${video}`),
    enabled: !!video,
  });
  const sourceFrames = Number(source.data?.metadata?.frames ?? 0);
  const sourceFps = Number(source.data?.metadata?.fps ?? 0);
  const [negative, setNegative] = useState(
    String(restored.negative_prompt ?? "speech, music"),
  );
  const [steps, setSteps] = useState(Number(restored.steps ?? 25));
  const [cfg, setCfg] = useState(Number(restored.cfg ?? 4.5));
  const [seed, setSeed] = useState(
    restored.seed == null ? "" : String(restored.seed),
  );
  const [gpu, setGpu] = useState(String(restored.gpu ?? "auto"));
  const [translation, setTranslation] = useState<TranslationOptions>(
    (restored.translation as TranslationOptions) ?? {
      mode: "inherit",
      review: false,
      protected_terms: [],
    },
  );
  const ready = useQuery({
    queryKey: ["effects-capabilities"],
    queryFn: () => api<Ready>("/audio/effects/capabilities"),
    staleTime: 30000,
    refetchInterval: (q) =>
      q.state.data?.readiness === "checking" ? 2000 : false,
  });
  const hardware = useHardware();
  const id = search.get("run") ?? "";
  const run = useMediaRun(id);
  const preview = useMediaRun(
    typeof run.data?.metadata?.effects_preview_run_id === "string"
      ? run.data.metadata.effects_preview_run_id
      : "",
  );
  const busy = mediaBusy(run.data) || mediaBusy(preview.data);
  const parameters = {
    video_artifact_id: video,
    prompt,
    negative_prompt: negative,
    ...(cues.length ? { cues } : {}),
    steps,
    cfg,
    seed: seed === "" ? null : Number(seed),
    gpu,
    ...translationRequest(translation),
  };
  useCreativeDraft({ formState: parameters });
  const generate = useMutation({
    mutationFn: async () => {
      if (!ready.data?.available)
        throw new Error(
          ready.data?.reason ?? "Sound effects is still being checked.",
        );
      if (creative) return creativeRun(await creative.generate(parameters));
      return api<Run>("/audio/effects/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(parameters),
      });
    },
    onSuccess: (r) => {
      cache.setQueryData(["run", r.id], r);
      if (!creative) setSearch({ mode: "effects", run: r.id, input: video });
    },
  });
  return (
    <>
      <PageTitle
        eyebrow="CREATE / SOUND EFFECTS"
        title="Sound effects"
        action={
          <span className="media-runtime">
            <i /> MMAudio · Local
          </span>
        }
      >
        Give your film an atmosphere. Keep the effects track and a synchronized
        video preview. The preview plays the new effects track; use Edit a film
        to mix it with original speech or music.
      </PageTitle>
      <div className="media-workspace effects-workspace">
        <form
          className="panel media-composer"
          onSubmit={(e) => {
            e.preventDefault();
            if (!busy && !generate.isPending && cuesValid(cues, sourceFrames))
              generate.mutate();
          }}
        >
          <div className="media-composer-heading">
            <Waves size={20} />
            <h2>Create sound effects</h2>
            <span>Video → sound</span>
          </div>
          <fieldset disabled={busy || generate.isPending}>
            <MediaInput
              kind="video"
              label="Source film"
              hint="Choose a completed film from Library · up to 5 minutes"
              value={video}
              onChange={(id) => {
                if (id !== video) setCues([]);
                setVideo(id);
              }}
              disabled={busy || generate.isPending}
              onBusy={() => {}}
            />
            <label className="media-text-label">
              <span>
                What should we hear?<small>{prompt.length}/2000</small>
              </span>
              <textarea
                aria-label="What should we hear?"
                rows={5}
                maxLength={2000}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="Footsteps on wet gravel, a gentle breeze through the trees and birds in the distance…"
              />
            </label>
            <p className="muted effects-note">
              The film guides timing; your description shapes the sounds. This
              creates a separate effects track. The preview uses it instead of
              the film's existing audio; the original stays in Library.
            </p>
            <SoundCueEditor
              value={cues}
              onChange={setCues}
              fps={sourceFps}
              frames={sourceFrames}
              disabled={busy || generate.isPending}
            />
            <PromptTranslationControl
              value={translation}
              onChange={setTranslation}
              disabled={busy || generate.isPending}
            />
            <details className="media-advanced">
              <summary>
                <Settings2 size={15} />
                Advanced settings
              </summary>
              <div className="media-settings-grid">
                <label>
                  Avoid these sounds
                  <textarea
                    rows={2}
                    maxLength={2000}
                    value={negative}
                    onChange={(e) => setNegative(e.target.value)}
                  />
                </label>
                <label>
                  Steps
                  <input
                    type="number"
                    min={10}
                    max={50}
                    value={steps}
                    onChange={(e) => setSteps(Number(e.target.value))}
                  />
                </label>
                <label>
                  Guidance
                  <input
                    type="number"
                    min={1}
                    max={10}
                    step={0.1}
                    value={cfg}
                    onChange={(e) => setCfg(Number(e.target.value))}
                  />
                </label>
                <label>
                  Seed
                  <input
                    type="number"
                    min={0}
                    max={2147483647}
                    value={seed}
                    onChange={(e) => setSeed(e.target.value)}
                    placeholder="Random"
                  />
                </label>
                <GpuTargetChoiceList
                  value={gpu}
                  gpus={
                    hardware.data?.gpus.filter(
                      (device) =>
                        ready.data?.configuration_source !== "managed" ||
                        ready.data.eligible_gpu_indices?.includes(device.index),
                    ) ?? []
                  }
                  disabled={busy}
                  onChange={setGpu}
                />
              </div>
            </details>
            {!ready.data?.available && (
              <p className="muted" role="status">
                {ready.data?.reason ?? "Checking local sound effects setup…"}{" "}
                <Link to="/setup/models?capability=effects">
                  Set up sound effects
                </Link>
              </p>
            )}
            <ErrorNotice error={generate.error ?? ready.error} />
            <Button
              className="media-generate"
              disabled={
                !video ||
                !prompt.trim() ||
                !cuesValid(cues, sourceFrames) ||
                !ready.data?.available ||
                busy ||
                generate.isPending
              }
            >
              <Sparkles size={17} />
              {generate.isPending ? "Saving your request…" : "Generate sound"}
            </Button>
            <small className="muted effects-license">
              MMAudio · CC BY-NC 4.0 model ·{" "}
              <a
                href="https://huggingface.co/hkchengrex/MMAudio"
                target="_blank"
                rel="noreferrer"
              >
                Model license
              </a>
            </small>
          </fieldset>
        </form>
        {!creative && (
          <div className="effects-results">
            <MediaResult
              kind="audio"
              audioMode="effects"
              runId={id}
              run={run.data}
              error={run.error}
              allowRetry={false}
            />
            {preview.data && (
              <MediaResult
                kind="video"
                videoMode="scene"
                runId={preview.data.id}
                run={preview.data}
                error={preview.error}
                allowRetry={false}
              />
            )}
          </div>
        )}
      </div>
    </>
  );
}
