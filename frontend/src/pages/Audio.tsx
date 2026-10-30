import CreativeWorkspace from "../components/creative/CreativeWorkspace";
import {
  useCreative,
  useCreativeDraft,
  creativeRun,
} from "../components/creative/creative-context";
import type { ReactNode } from "react";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { AudioLines, Settings2, Sparkles } from "lucide-react";
import { api, useHardware, type Run } from "../api";
import { ErrorNotice, PageTitle } from "../components/common";
import { Button } from "../components/ui/button";
import MediaInput from "../components/media/MediaInput";
import MediaResult from "../components/media/MediaResult";
import { mediaBusy, useMediaRun } from "../components/media/media-run";
import Transcription from "./Transcription";
import Music from "./Music";
import { GpuTargetChoiceList } from "./GpuTargetChoiceList";
import SpeechDeliveryControls from "../components/media/SpeechDeliveryControls";
import SpeechEngineFields from "../components/media/SpeechEngineFields";
import {
  defaultSpeechDelivery,
  type SpeechDelivery,
  type SpeechCapabilities,
} from "../components/media/speech-delivery";

export default function Audio({
  withCreativeSessions = false,
}: {
  withCreativeSessions?: boolean;
}) {
  const [search, setSearch] = useSearchParams();
  // Remount when Library or a finished result chooses a different voice, not
  // when a generation Run is recorded in the URL.
  const current = useMediaRun(search.get("run") ?? "");
  const busy = mediaBusy(current.data);
  const music =
    search.get("mode") === "music" ||
    current.data?.capability === "audio.music";
  const speech = search.get("mode") !== "transcribe" && !music;
  function wrap(capability: "music" | "speech", child: ReactNode) {
    return withCreativeSessions ? (
      <CreativeWorkspace capability={capability}>{child}</CreativeWorkspace>
    ) : (
      child
    );
  }
  return (
    <>
      <nav className="mode-tabs audio-mode-tabs" aria-label="Audio mode">
        <button
          type="button"
          aria-label="Create speech"
          disabled={busy}
          className={speech ? "active" : ""}
          aria-pressed={speech}
          onClick={() => {
            const next = new URLSearchParams();
            if (search.get("input")) next.set("input", search.get("input")!);
            setSearch(next);
          }}
        >
          Speech
        </button>
        <button
          type="button"
          disabled={busy}
          className={music ? "active" : ""}
          aria-pressed={music}
          onClick={() => setSearch({ mode: "music" })}
        >
          Music
        </button>
        <button
          type="button"
          disabled={busy}
          className={search.get("mode") === "transcribe" ? "active" : ""}
          aria-pressed={search.get("mode") === "transcribe"}
          onClick={() => {
            const next = new URLSearchParams({ mode: "transcribe" });
            if (search.get("input")) next.set("input", search.get("input")!);
            setSearch(next);
          }}
        >
          Transcription
        </button>
      </nav>
      {music ? (
        wrap(
          "music",
          <Music
            key={`${current.data?.id ?? ""}:${current.data ? "restored" : ""}`}
            initialRun={current.data}
          />,
        )
      ) : search.get("mode") === "transcribe" ? (
        <Transcription key={search.get("input") ?? ""} />
      ) : (
        wrap(
          "speech",
          <AudioForm
            key={search.get("input") ?? ""}
            initialInput={search.get("input")}
          />,
        )
      )}
    </>
  );
}

function AudioForm({ initialInput }: { initialInput: string | null }) {
  const creative = useCreative();
  return (
    <SpeechForm
      key={creative?.formKey ?? initialInput ?? "legacy"}
      initialInput={initialInput}
    />
  );
}
function SpeechForm({ initialInput }: { initialInput: string | null }) {
  const creative = useCreative();
  const [initial] = useState(() => creative?.draft ?? {});
  const restored = (initial.formState ?? initial) as Record<string, unknown>;
  const [search, setSearch] = useSearchParams();
  const cache = useQueryClient();
  const [reference, setReference] = useState(
    String(
      restored.reference ??
        restored.reference_artifact_id ??
        initialInput ??
        "",
    ),
  );
  const [text, setText] = useState(String(restored.text ?? ""));
  const [gpu, setGpu] = useState(String(restored.gpu ?? "auto"));
  const [engine, setEngine] = useState(String(restored.engine ?? ""));
  const [direction, setDirection] = useState(
    String(restored.direction ?? "natural"),
  );
  const [pace, setPace] = useState(String(restored.pace ?? "natural"));
  const fish = engine === "fish_s2_pro";
  const [shapeDelivery, setShapeDelivery] = useState(!!restored.delivery);
  const [delivery, setDelivery] = useState<SpeechDelivery>(
    (restored.delivery as SpeechDelivery | undefined) ?? defaultSpeechDelivery,
  );
  const capabilities = useQuery({
    queryKey: ["speech-capabilities"],
    queryFn: () => api<SpeechCapabilities>("/audio/capabilities"),
    staleTime: 30000,
    refetchInterval: (query) =>
      query.state.data?.engines?.fish_s2_pro?.readiness === "checking"
        ? 2000
        : false,
  });
  const fishReady = capabilities.data?.engines?.fish_s2_pro?.available === true;
  const supportsDelivery =
    capabilities.data?.delivery?.version === "chatterbox-controls-v1";
  useCreativeDraft({
    formState: {
      reference,
      text,
      gpu,
      ...(fish
        ? { engine, direction, pace }
        : shapeDelivery
          ? { delivery }
          : {}),
    },
  });
  const [uploading, setUploading] = useState(false);
  const hardware = useHardware();
  const runId = search.get("run") ?? "";
  const run = useMediaRun(runId);
  const generate = useMutation({
    mutationFn: async () => {
      if (fish && !fishReady)
        throw new Error(
          "Expressive speech is unavailable or still being verified.",
        );
      if (!fish && shapeDelivery && !supportsDelivery)
        throw new Error(
          "Delivery controls are unavailable. Turn them off to use the standard voice.",
        );
      const parameters = {
        text,
        gpu,
        reference_artifact_id: reference,
        ...(fish
          ? { engine, direction, pace }
          : shapeDelivery
            ? { delivery }
            : {}),
      };
      if (creative)
        return creativeRun(
          await creative.generate(parameters, {
            feedback: creative.draft._creative_parent_turn_id ? text : "",
          }),
        );
      return api<Run>("/audio/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(parameters),
      });
    },
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
        eyebrow="CREATE / AUDIO"
        title="Give your words a voice."
        action={
          <span className="media-runtime">
            <i />
            {fish ? "Fish S2 Pro" : "Chatterbox"} · Local
          </span>
        }
      >
        Local speech, shaped by your voice reference. Listen and refine right
        here.
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
            <AudioLines size={20} />
            <h2>Create speech</h2>
            <span>01 / Voice & text</span>
          </div>
          <fieldset disabled={uploading || busy}>
            <SpeechEngineFields
              engine={engine}
              direction={direction}
              pace={pace}
              capabilities={capabilities.data}
              onEngine={setEngine}
              onDirection={setDirection}
              onPace={setPace}
            />
            <MediaInput
              kind="audio"
              label="Voice reference"
              hint={
                fish
                  ? "WAV · best with 5–15 sec of clear speech · up to 60 sec / 20 MB"
                  : "WAV · 0.1–60 sec · up to 20 MB"
              }
              value={reference}
              onChange={setReference}
              disabled={uploading || busy}
              onBusy={setUploading}
            />
            <label className="media-text-label">
              <span>
                Text to speak <small>{text.length} / 1000</small>
              </span>
              <textarea
                aria-label="Text to speak"
                required
                maxLength={1000}
                rows={6}
                value={text}
                onChange={(event) => setText(event.target.value)}
                placeholder="Write the words you want to hear…"
              />
            </label>
            {!fish && (
              <SpeechDeliveryControls
                enabled={shapeDelivery}
                supported={supportsDelivery}
                disabled={uploading || busy}
                value={delivery}
                onEnable={setShapeDelivery}
                onChange={setDelivery}
              />
            )}
            <details className="media-advanced">
              <summary>
                <Settings2 size={15} />
                Advanced settings<span>GPU</span>
              </summary>
              <div>
                <span>GPU</span>
                <GpuTargetChoiceList
                  value={gpu}
                  gpus={hardware.data?.gpus ?? []}
                  disabled={uploading || busy}
                  onChange={setGpu}
                  hint={
                    fish
                      ? "Auto reserves a compatible GPU pair. A specific GPU selects the primary device; AI Station allocates the second device."
                      : undefined
                  }
                />
              </div>
              <ErrorNotice error={hardware.error} />
            </details>
            <ErrorNotice error={generate.error} />
            <Button
              type="submit"
              className="media-generate"
              disabled={
                !reference ||
                !text.trim() ||
                uploading ||
                busy ||
                (fish ? !fishReady : shapeDelivery && !supportsDelivery)
              }
            >
              <Sparkles size={17} />
              {busy ? "Generating speech…" : "Generate speech"}
            </Button>
            <p className="media-privacy">
              Your voice and text stay on this workstation.
            </p>
          </fieldset>
        </form>
        {!creative && (
          <MediaResult
            kind="audio"
            runId={runId}
            run={run.data}
            error={run.error}
          />
        )}
      </div>
    </>
  );
}
