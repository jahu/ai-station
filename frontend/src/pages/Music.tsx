import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Music2, Settings2, Sparkles } from "lucide-react";
import { api, useHardware, type Run } from "../api";
import { ErrorNotice, PageTitle } from "../components/common";
import { Button } from "../components/ui/button";
import MediaResult from "../components/media/MediaResult";
import { mediaBusy, useMediaRun } from "../components/media/media-run";
import { chatRequestId, clearChatRequest } from "./chat-draft";
import { GpuTargetChoiceList } from "./GpuTargetChoiceList";
import {
  PromptTranslationControl,
  translationRequest,
  type TranslationOptions,
  type TranslationReceipt,
} from "../components/media/PromptTranslation";

type MusicCapabilities = {
  available: boolean;
  reason?: string;
  max_seconds?: number;
};

export default function Music({ initialRun }: { initialRun?: Run }) {
  const [search, setSearch] = useSearchParams();
  const cache = useQueryClient();
  const parameters = initialRun?.parameters ?? {};
  const savedTranslation = initialRun?.metadata?.prompt_translation as
    TranslationReceipt | undefined;
  const [caption, setCaption] = useState(
    String(savedTranslation?.original.caption ?? parameters.caption ?? ""),
  );
  const [translation, setTranslation] = useState<TranslationOptions>({
    mode: "inherit",
    review: false,
    protected_terms: [],
  });
  const [lyrics, setLyrics] = useState(String(parameters.lyrics ?? ""));
  const [instrumental, setInstrumental] = useState(
    parameters.instrumental !== false,
  );
  const [duration, setDuration] = useState(
    Number(parameters.duration_seconds ?? 30),
  );
  const [seed, setSeed] = useState(
    parameters.seed === undefined ? "" : String(parameters.seed),
  );
  const [gpu, setGpu] = useState(initialRun?.requested_gpu ?? "auto");
  const receipt = useRef<{ payload: string; id: string } | null>(null);
  const hardware = useHardware();
  const profile = useQuery({
    queryKey: ["music-capabilities"],
    queryFn: () => api<MusicCapabilities>("/audio/music/capabilities"),
    staleTime: 30000,
  });
  const runId = search.get("run") ?? "";
  const run = useMediaRun(runId);
  const generate = useMutation({
    mutationFn: async () => {
      const payload = JSON.stringify({
        caption: caption.trim(),
        lyrics: instrumental ? "" : lyrics.trim(),
        instrumental,
        duration_seconds: duration,
        gpu,
        seed: seed.trim() ? Number(seed) : null,
        ...translationRequest(translation),
      });
      if (receipt.current?.payload !== payload) {
        receipt.current = {
          payload,
          id: await chatRequestId("audio-music", payload),
        };
      }
      return api<Run>("/audio/music/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...JSON.parse(payload),
          client_request_id: receipt.current.id,
        }),
      });
    },
    onSuccess: (result) => {
      cache.setQueryData(["run", result.id], result);
      clearChatRequest("audio-music");
      receipt.current = null;
      setSearch({ mode: "music", run: result.id });
    },
  });
  const busy = generate.isPending || mediaBusy(run.data);
  const available = profile.data?.available === true;
  const maximum = Math.min(600, profile.data?.max_seconds ?? 600);
  return (
    <>
      <PageTitle
        eyebrow="CREATE / AUDIO"
        title="Find your sound."
        action={
          <span className="media-runtime">
            {available && <i />}
            ACE-Step 1.5 · Local
          </span>
        }
      >
        From a quiet piano theme to a full song. Describe the mood and
        instruments, or bring your own lyrics.
      </PageTitle>
      <div className="media-workspace">
        <form
          className="panel media-composer"
          onSubmit={(event) => {
            event.preventDefault();
            if (available && !busy) generate.mutate();
          }}
        >
          <div className="media-composer-heading">
            <Music2 size={20} />
            <h2>Create music</h2>
            <span>01 / Your sound</span>
          </div>
          <ErrorNotice error={profile.error} />
          {profile.isPending && (
            <p role="status">Checking local music engine…</p>
          )}
          {profile.data && !available && (
            <p role="status" className="media-privacy">
              Local music is not ready. The offline engine and its approved
              model need setup.
            </p>
          )}
          <fieldset disabled={busy}>
            <label className="media-text-label">
              <span>
                Describe your music <small>{caption.length} / 512</small>
              </span>
              <textarea
                aria-label="Describe your music"
                required
                maxLength={512}
                rows={5}
                value={caption}
                onChange={(event) => setCaption(event.target.value)}
                placeholder="Warm, cinematic piano with soft strings. A slow build, hopeful atmosphere and a gentle ending…"
              />
            </label>
            <div className="mode-tabs" aria-label="Music vocals">
              <button
                type="button"
                className={instrumental ? "active" : ""}
                aria-pressed={instrumental}
                onClick={() => setInstrumental(true)}
              >
                Instrumental
              </button>
              <button
                type="button"
                className={!instrumental ? "active" : ""}
                aria-pressed={!instrumental}
                onClick={() => setInstrumental(false)}
              >
                With lyrics
              </button>
            </div>
            {!instrumental && (
              <label className="media-text-label">
                <span>
                  Your lyrics <small>{lyrics.length} / 4096</small>
                </span>
                <textarea
                  aria-label="Your lyrics"
                  required
                  maxLength={4096}
                  rows={7}
                  value={lyrics}
                  onChange={(event) => setLyrics(event.target.value)}
                  placeholder={"[Verse]\nWrite your words here…\n\n[Chorus]\n"}
                />
              </label>
            )}
            <label className="media-text-label">
              <span>Length</span>
              <select
                aria-label="Music length"
                value={duration}
                onChange={(event) => setDuration(Number(event.target.value))}
              >
                {[10, 30, 60, 120, 180, 300, 600]
                  .filter((seconds) => seconds <= maximum)
                  .map((seconds) => (
                    <option key={seconds} value={seconds}>
                      {seconds < 60
                        ? `${seconds} seconds`
                        : `${seconds / 60} minute${seconds === 60 ? "" : "s"}`}
                    </option>
                  ))}
              </select>
            </label>
            <details className="media-advanced">
              <summary>
                <Settings2 size={15} />
                Advanced settings<span>GPU · Seed</span>
              </summary>
              <div>
                <span>GPU</span>
                <GpuTargetChoiceList
                  value={gpu}
                  gpus={hardware.data?.gpus ?? []}
                  disabled={busy}
                  onChange={setGpu}
                />
              </div>
              <label>
                Seed
                <input
                  aria-label="Music seed"
                  type="number"
                  min={0}
                  max={2147483647}
                  step={1}
                  value={seed}
                  placeholder="Random"
                  onChange={(event) => setSeed(event.target.value)}
                />
              </label>
              <ErrorNotice error={hardware.error} />
            </details>
            <ErrorNotice error={generate.error} />
            <PromptTranslationControl
              value={translation}
              onChange={setTranslation}
              disabled={busy}
            />
            <Button
              type="submit"
              className="media-generate"
              disabled={
                !available ||
                busy ||
                !caption.trim() ||
                (!instrumental && !lyrics.trim()) ||
                duration > maximum
              }
            >
              <Sparkles size={17} />
              {busy ? "Creating music…" : "Generate music"}
            </Button>
            <p className="media-privacy">
              Created on your workstation. Your music and lyrics stay local.
            </p>
          </fieldset>
        </form>
        <MediaResult
          kind="audio"
          audioMode="music"
          runId={runId}
          run={run.data}
          error={run.error}
        />
      </div>
    </>
  );
}
