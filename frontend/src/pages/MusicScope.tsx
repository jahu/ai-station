import { useRef } from "react";
import { Settings2 } from "lucide-react";
import { useHardware } from "../api";
import { ErrorNotice } from "../components/common";
import { GpuTargetChoiceList } from "./GpuTargetChoiceList";
import type { MusicScopeOptions } from "./music-scope";

export default function MusicScope({
  value,
  onChange,
  descriptionLength,
  allowAutomaticDuration = true,
  lyricsSource = "fixed",
  onLyricsSourceChange,
}: {
  value: MusicScopeOptions;
  onChange: (value: MusicScopeOptions) => void;
  descriptionLength?: number;
  allowAutomaticDuration?: boolean;
  lyricsSource?: "fixed" | "goal";
  onLyricsSourceChange?: (source: "fixed" | "goal") => void;
}) {
  const instrumental = value.instrumental !== false;
  const generatedLyrics = lyricsSource === "goal" && !!onLyricsSourceChange;
  const rememberedLyrics = useRef(value.lyrics ?? "");
  const hardware = useHardware();
  function vocals(enabled: boolean) {
    if (!enabled) rememberedLyrics.current = value.lyrics ?? "";
    onChange({
      ...value,
      instrumental: !enabled,
      lyrics: enabled ? rememberedLyrics.current : "",
    });
  }
  return (
    <section aria-label="Music settings">
      <p className="muted">
        Describe the style, instruments and mood in your message.{" "}
        {descriptionLength ?? 0} / 512 characters.
      </p>
      {descriptionLength !== undefined && descriptionLength > 512 && (
        <p role="alert" className="notice">
          Shorten the music description to 512 characters.
        </p>
      )}
      <label>
        Music length
        <select
          aria-label="Music length"
          value={value.duration_seconds ?? "auto"}
          onChange={(event) =>
            onChange({
              ...value,
              duration_seconds:
                event.target.value === "auto"
                  ? null
                  : Number(event.target.value),
            })
          }
        >
          {allowAutomaticDuration && (
            <option value="auto">
              From your message · 30 seconds by default
            </option>
          )}
          {[10, 30, 60, 120, 180, 300, 600].map((seconds) => (
            <option key={seconds} value={seconds}>
              {seconds < 60
                ? `${seconds} seconds`
                : `${seconds / 60} minute${seconds === 60 ? "" : "s"}`}
            </option>
          ))}
        </select>
      </label>
      <div className="mode-tabs" aria-label="Music vocals">
        <button
          type="button"
          aria-pressed={instrumental}
          onClick={() => vocals(false)}
        >
          Instrumental
        </button>
        <button
          type="button"
          aria-pressed={!instrumental}
          onClick={() => vocals(true)}
        >
          With lyrics
        </button>
      </div>
      {!instrumental && (
        <>
          {onLyricsSourceChange && (
            <label>
              Song lyrics
              <select
                aria-label="Song lyrics policy"
                value={lyricsSource}
                onChange={(event) =>
                  onLyricsSourceChange(event.target.value as "fixed" | "goal")
                }
              >
                <option value="goal">Write lyrics each run</option>
                <option value="fixed">Use my lyrics</option>
              </select>
            </label>
          )}
          <label>
            {generatedLyrics ? "Lyrics guidance (optional)" : "Your lyrics"}
            <textarea
              aria-label={
                generatedLyrics ? "Lyrics guidance (optional)" : "Your lyrics"
              }
              value={value.lyrics ?? ""}
              rows={5}
              maxLength={4096}
              onChange={(event) => {
                rememberedLyrics.current = event.target.value;
                onChange({ ...value, lyrics: event.target.value });
              }}
              placeholder={
                generatedLyrics
                  ? "For example: a short Polish chorus about a fresh start, without names."
                  : "[Verse]\nWrite your words…\n\n[Chorus]\n"
              }
            />
            <small>
              {generatedLyrics
                ? "Your local model writes original words from the agent goal and this guidance. The actual lyrics are saved with the result."
                : "Use [Verse] and [Chorus] to shape the song."}
            </small>
          </label>
        </>
      )}
      <details className="media-advanced">
        <summary>
          <Settings2 size={15} />
          Advanced music settings<span>GPU · Seed</span>
        </summary>
        <GpuTargetChoiceList
          value={value.gpu ?? "auto"}
          gpus={hardware.data?.gpus ?? []}
          onChange={(gpu) => onChange({ ...value, gpu })}
        />
        <label>
          Seed
          <input
            aria-label="Music seed"
            type="number"
            min={0}
            max={2147483647}
            step={1}
            placeholder="Random"
            value={value.seed ?? ""}
            onChange={(event) =>
              onChange({
                ...value,
                seed: event.target.value.trim()
                  ? Number(event.target.value)
                  : null,
              })
            }
          />
        </label>
        <ErrorNotice error={hardware.error} />
      </details>
      <p className="muted">
        ACE-Step · Local generation. Results appear here and in Library.
      </p>
    </section>
  );
}
