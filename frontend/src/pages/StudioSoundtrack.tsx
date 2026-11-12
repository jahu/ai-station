import { useRef, useState } from "react";
import StudioTimingChoice, { type TimingPolicy } from "./StudioTimingChoice";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AudioLines, Check, Music2, Square, X } from "lucide-react";
import { api, type Artifact, type Run } from "../api";
import { useAccount } from "../account-context";
import { Badge, ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";
import { creativeJson } from "../components/creative/creative-project";
import LibraryPicker from "../components/media/LibraryPicker";
import MusicModelChoice from "../components/media/MusicModelChoice";
import SpeechEngineFields from "../components/media/SpeechEngineFields";
import { useSpeechModels } from "../components/media/speech-models";
import type { SpeechCapabilities } from "../components/media/speech-delivery";
import { randomId } from "../lib/random-id";
import { materialBase, type StudioRevision } from "./studio-material";

type Production = {
  root_run: Run;
  status: string;
  runs: Run[];
  active_run_ids: string[];
  failed_run: Run | null;
  soundtrack: Artifact | null;
  measured_revision_id: string | null;
};

export default function StudioSoundtrack({
  materialId,
  revision,
  disabled,
  onMeasured,
}: {
  materialId: string;
  revision: StudioRevision;
  disabled: boolean;
  onMeasured: (id: string) => Promise<unknown>;
}) {
  const { user } = useAccount();
  const cache = useQueryClient();
  const audio = revision.storyboard.audio;
  const voice = audio === "voice" || audio === "voice_music";
  const music = audio === "music" || audio === "voice_music";
  const [timingPolicy, setTimingPolicy] = useState<TimingPolicy>();
  const [engine, setEngine] = useState("fish_s2_pro");
  const [modelId, setModel] = useState("");
  const [direction, setDirection] = useState(
    revision.storyboard.narration_delivery?.direction ?? "natural",
  );
  const [pace, setPace] = useState(
    revision.storyboard.narration_delivery?.pace ?? "natural",
  );
  const [voiceSource, setVoiceSource] = useState<"model" | "reference">(
    "model",
  );
  const [reference, setReference] = useState<Artifact | null>(null);
  const [language, setLanguage] = useState("");
  const [musicModel, setMusicModel] = useState("");
  const caption = revision.storyboard.music_brief;
  const [gain, setGain] = useState(0.22);
  const [selected, setSelected] = useState("");
  const receipt = useRef<{ fingerprint: string; id: string } | null>(null);
  const key = ["studio-audio-productions", user?.id, materialId, revision.id];
  const productions = useQuery({
    queryKey: key,
    queryFn: ({ signal }) =>
      api<Production[]>(
        `${materialBase}/${materialId}/audio/productions?revision_id=${revision.id}`,
        { signal },
      ),
    refetchInterval: (q) =>
      q.state.data?.some((p) => p.active_run_ids.length) ? 1500 : false,
  });
  const speechModels = useSpeechModels(voice);
  const speech = useQuery({
    queryKey:
      modelId && engine !== "fish_s2_pro"
        ? ["speech-capabilities", modelId]
        : ["speech-capabilities"],
    enabled: voice,
    queryFn: () =>
      api<SpeechCapabilities>(
        modelId && engine !== "fish_s2_pro"
          ? `/audio/models/${modelId}/capabilities`
          : "/audio/capabilities",
      ),
    refetchInterval: (q) =>
      q.state.data?.engines?.fish_s2_pro?.readiness === "checking"
        ? 3000
        : false,
  });
  const score = useQuery({
    queryKey: ["studio-music-capabilities", musicModel],
    enabled: music,
    queryFn: () =>
      api<{ available: boolean; reason?: string }>(
        musicModel
          ? `/audio/music/models/${musicModel}/capabilities`
          : "/audio/music/capabilities",
      ),
  });
  const fish = engine === "fish_s2_pro";
  const needsReference = voice && (!fish || voiceSource === "reference");
  const voiceReady =
    !voice ||
    (fish
      ? speech.data?.engines?.fish_s2_pro?.available === true &&
        (needsReference ||
          speech.data?.engines?.fish_s2_pro?.voice_sources?.includes("model"))
      : speech.data?.available === true);
  const scoreReady = !music || score.data?.available === true;
  const rows = productions.data ?? [];
  const active = rows.find((p) => p.active_run_ids.length);
  const chosen =
    rows.find((p) => p.root_run.id === selected) ?? active ?? rows[0];
  function refresh() {
    void cache.invalidateQueries({ queryKey: key });
    void cache.invalidateQueries({
      queryKey: ["studio-activity", user?.id, materialId],
    });
  }
  const generate = useMutation({
    mutationFn: (reuse: Production | null) => {
      const body = reuse
        ? {
            ...(reuse.root_run.parameters.request as Record<string, unknown>),
            revision_id: revision.id,
            timing_policy: timingPolicy,
            reuse_from_run_id: reuse.root_run.id,
          }
        : {
            revision_id: revision.id,
            ...(timingPolicy ? { timing_policy: timingPolicy } : {}),
            ...(voice
              ? {
                  voice: {
                    engine: fish ? "fish_s2_pro" : "chatterbox",
                    reference_artifact_id: needsReference
                      ? (reference?.id ?? null)
                      : null,
                    ...(fish
                      ? { direction, pace }
                      : {
                          language:
                            language ||
                            (speech.data?.languages?.includes("en")
                              ? "en"
                              : "pl"),
                          ...(modelId ? { model_id: modelId } : {}),
                        }),
                  },
                }
              : {}),
            ...(music
              ? {
                  music_gain: gain,
                  ...(musicModel ? { music_model_id: musicModel } : {}),
                }
              : {}),
          };
      const fingerprint = JSON.stringify(body);
      if (receipt.current?.fingerprint !== fingerprint)
        receipt.current = { fingerprint, id: randomId() };
      return api<Run>(
        `${materialBase}/${materialId}/audio/produce`,
        creativeJson("POST", {
          ...body,
          client_request_id: receipt.current.id,
        }),
      );
    },
    onSuccess: (run) => {
      receipt.current = null;
      setSelected(run.id);
      cache.setQueryData<Production[]>(key, (previous) => [
        {
          root_run: run,
          status: "queued",
          runs: [run],
          active_run_ids: [run.id],
          failed_run: null,
          soundtrack: null,
          measured_revision_id: null,
        },
        ...(previous ?? []),
      ]);
      refresh();
    },
  });
  const stop = useMutation({
    mutationFn: (id: string) =>
      api(
        `${materialBase}/${materialId}/audio/${id}/stop`,
        creativeJson("POST", {}),
      ),
    onSuccess: refresh,
  });
  const apply = useMutation({ mutationFn: (id: string) => onMeasured(id) });
  if (audio === "silent") return null;
  const working =
    active?.runs.find((r) => r.status === "running") ??
    active?.runs.find((r) => active.active_run_ids.includes(r.id));
  const completedCues =
    active?.runs.filter(
      (r) => r.capability === "audio.speech" && r.status === "succeeded",
    ).length ?? 0;
  const previousRequest = chosen?.root_run.parameters.request as
    Record<string, unknown> | undefined;
  const canRemixTiming = Boolean(
    voice &&
    chosen?.status === "succeeded" &&
    chosen.soundtrack &&
    previousRequest &&
    timingPolicy &&
    timingPolicy !== (previousRequest.timing_policy ?? "preserve"),
  );
  return (
    <section
      className="panel studio-soundtrack"
      aria-label="Produce soundtrack"
    >
      <header>
        <AudioLines size={22} />
        <div>
          <h3>Bring the story to life</h3>
          <p>
            {voice && music
              ? "One narrator, a matching score, a balanced final soundtrack."
              : voice
                ? "A consistent narrator for every part of the story."
                : "An original score shaped around your edit."}
          </p>
        </div>
      </header>
      <p className="studio-direction-note">
        Complete spoken passages set the timing. Shots can grow to fit the
        voice; words are never cut to meet a guessed duration. New soundtracks
        have measured volume and peak protection for sharing.
      </p>
      {chosen?.soundtrack && (
        <div className="studio-soundtrack-result">
          <strong>
            <Check size={15} />
            Your soundtrack
          </strong>
          <audio
            controls
            preload="metadata"
            src={`/api/artifacts/${chosen.soundtrack.id}/file`}
            aria-label="Finished soundtrack"
          />
          {!!chosen.soundtrack.metadata?.mastering && (
            <p className="studio-direction-note">
              {(
                chosen.soundtrack.metadata.mastering as {
                  target_reached?: boolean;
                }
              ).target_reached
                ? "Volume balanced for sharing."
                : "Volume protection applied; measured details are available in Library."}
            </p>
          )}
          <div>
            <Link to={`/library/${chosen.soundtrack.id}`}>
              Open in Library ↗
            </Link>
            {chosen.measured_revision_id &&
              chosen.measured_revision_id !== revision.id && (
                <Button
                  type="button"
                  variant="ghost"
                  disabled={disabled || apply.isPending}
                  onClick={() => apply.mutate(chosen.measured_revision_id!)}
                >
                  Apply measured timing & audio
                </Button>
              )}
          </div>
        </div>
      )}
      {rows.length > 1 && (
        <label>
          Soundtrack takes
          <select
            aria-label="Soundtrack take"
            value={chosen?.root_run.id ?? ""}
            onChange={(e) => setSelected(e.target.value)}
          >
            {rows.map((p, i) => (
              <option value={p.root_run.id} key={p.root_run.id}>
                Take {rows.length - i} · {p.status}
              </option>
            ))}
          </select>
        </label>
      )}
      {active && (
        <div className="studio-soundtrack-progress" role="status">
          <Music2 size={20} />
          <div>
            <strong>
              {working?.capability === "audio.speech"
                ? "Recording the voiceover"
                : working?.capability === "audio.music"
                  ? "Creating your score"
                  : working?.executor_type === "studio_soundtrack"
                    ? "Balancing the soundtrack"
                    : "Preparing your sound"}
            </strong>
            <span>
              {voice
                ? `${completedCues} of ${revision.storyboard.scenes.filter((s) => s.narration).length} voice passages ready. `
                : ""}
              Every completed result is kept.
            </span>
          </div>
          <Badge status={working?.status ?? active.status} />
          <Button
            type="button"
            variant="ghost"
            disabled={stop.isPending}
            onClick={() => stop.mutate(active.root_run.id)}
          >
            <Square size={13} />
            Stop sound
          </Button>
        </div>
      )}
      {chosen?.failed_run && (
        <div className="notice" role="alert">
          {chosen.failed_run.error_message}
          <Link to={`/runs/${chosen.failed_run.id}`}>Inspect Run</Link>
        </div>
      )}
      <details className="studio-soundtrack-settings">
        <summary>Voice, music & timing</summary>
        <fieldset disabled={disabled || !!active || generate.isPending}>
          {voice && (
            <StudioTimingChoice
              value={timingPolicy}
              onChange={setTimingPolicy}
            />
          )}
          {voice && (
            <>
              <SpeechEngineFields
                engine={engine}
                direction={direction}
                pace={pace}
                capabilities={speech.data}
                models={speechModels.data?.items}
                modelId={modelId}
                onModel={(id) => {
                  setModel(id);
                  setEngine("");
                  setDirection("natural");
                  setPace("natural");
                }}
                onEngine={(v) => {
                  setEngine(v);
                  setModel("");
                  if (v !== "fish_s2_pro") {
                    setDirection("natural");
                    setPace("natural");
                  }
                }}
                onDirection={setDirection}
                onPace={setPace}
                voiceSource={voiceSource}
                onVoiceSource={setVoiceSource}
              />
              {needsReference && (
                <>
                  <LibraryPicker
                    kind="audio"
                    existing={reference ? [reference.id] : []}
                    limit={1}
                    busy={disabled || !!active}
                    onSelect={(items) => setReference(items[0] ?? null)}
                  />
                  {reference && (
                    <div className="studio-reference-list">
                      <span>
                        {reference.title || reference.original_filename}
                        <button
                          type="button"
                          aria-label="Remove narrator reference"
                          onClick={() => setReference(null)}
                        >
                          <X size={14} />
                        </button>
                      </span>
                    </div>
                  )}
                </>
              )}
              {!fish && (
                <label>
                  Narration language
                  <select
                    aria-label="Narration language"
                    value={
                      language ||
                      (speech.data?.languages?.includes("en") ? "en" : "pl")
                    }
                    onChange={(e) => setLanguage(e.target.value)}
                  >
                    <option value="pl">Polish</option>
                    <option
                      value="en"
                      disabled={!speech.data?.languages?.includes("en")}
                    >
                      English
                    </option>
                  </select>
                </label>
              )}
            </>
          )}
          {music && (
            <>
              <MusicModelChoice
                value={musicModel}
                onChange={setMusicModel}
                disabled={disabled || !!active}
              />
              {voice && (
                <label>
                  Background music · {Math.round(gain * 100)}%
                  <input
                    aria-label="Background music level"
                    type="range"
                    min=".01"
                    max="1"
                    step=".01"
                    value={gain}
                    onChange={(e) => setGain(Number(e.target.value))}
                  />
                  <small>Automatically lowers under the narrator.</small>
                </label>
              )}
            </>
          )}
        </fieldset>
      </details>
      {!voiceReady && !speech.isPending && (
        <p className="studio-direction-note">
          Prepare a local speech model or choose an available voice in the sound
          settings. <Link to="/models">Open Models</Link>
        </p>
      )}
      {!scoreReady && !score.isPending && (
        <p className="studio-direction-note">
          {score.data?.reason ||
            "Prepare local music before producing a score."}{" "}
          <Link to="/models">Open Models</Link>
        </p>
      )}
      {needsReference && !reference && (
        <p className="studio-direction-note">
          Choose a narrator recording in Voice, music & timing.
        </p>
      )}
      {music && (!caption.trim() || caption.length > 512) && (
        <p className="notice" role="alert">
          Keep Music direction within 512 characters in the storyboard, then
          save this version before creating its soundtrack.
        </p>
      )}
      <ErrorNotice
        error={
          productions.error ??
          generate.error ??
          stop.error ??
          apply.error ??
          speech.error ??
          speechModels.error ??
          score.error
        }
      />
      <div className="studio-film-actions">
        <Button
          type="button"
          disabled={
            disabled ||
            !!active ||
            generate.isPending ||
            !voiceReady ||
            !scoreReady ||
            (needsReference && !reference) ||
            (music && (!caption.trim() || caption.length > 512))
          }
          onClick={() => generate.mutate(null)}
        >
          <AudioLines size={16} />
          {generate.isPending
            ? "Queuing…"
            : chosen?.soundtrack
              ? "Create another soundtrack"
              : "Create soundtrack"}
        </Button>
        {canRemixTiming && chosen && (
          <Button
            type="button"
            variant="secondary"
            disabled={disabled || !!active || generate.isPending}
            onClick={() => generate.mutate(chosen)}
          >
            Apply timing to this take
          </Button>
        )}
      </div>
      {canRemixTiming && (
        <p className="studio-direction-note">
          Reuse this take's narrator and mix settings. Speech is kept; a new
          score is only created if the existing one is too short.
        </p>
      )}
    </section>
  );
}
