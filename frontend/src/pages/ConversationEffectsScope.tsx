import SoundCueEditor from "../components/media/SoundCueEditor";
import AgentEffectsSource from "./AgentEffectsScope";
import type { EffectsMediaRequest } from "./agent-media";
export type EffectsOptions = Omit<EffectsMediaRequest, "prompt"> & {
  prompt?: string;
  preview_mode?: "mix" | "replace";
  original_gain?: number;
  effects_gain?: number;
};
export default function ConversationEffectsScope({
  value,
  newFilm = false,
  frames = 0,
  onChange,
  disabled,
  onBusy,
}: {
  newFilm?: boolean;
  frames?: number;
  value: EffectsOptions;
  onChange: (value: EffectsOptions) => void;
  disabled: boolean;
  onBusy: (value: boolean) => void;
}) {
  return (
    <section aria-label="Film sound settings" className="agent-media-scope">
      <h3>Sound for your film</h3>
      <p className="muted">
        {newFilm
          ? "First the film is generated, then a synchronized effects track and complete film. Speech and music can be added separately in the editor."
          : "Describe what should be heard in your message. Choose a film below, or use Auto and refer to a film already created in this conversation."}
      </p>
      {newFilm ? (
        <>
          <label>
            Sound description
            <textarea
              aria-label="New film sound description"
              maxLength={2000}
              value={value.prompt ?? ""}
              disabled={disabled}
              placeholder="Rain on the leaves, distant thunder, birds nearby…"
              onChange={(e) => onChange({ ...value, prompt: e.target.value })}
            />
          </label>
          {frames > 0 ? (
            <SoundCueEditor
              fps={24}
              frames={frames}
              value={value.cues ?? []}
              onChange={(cues) => onChange({ ...value, cues })}
              disabled={disabled}
            />
          ) : (
            <p className="muted">
              Select a video length to set scene timings. Changing the length
              clears scene timings. Described sounds are checked against the
              generated film.
            </p>
          )}
        </>
      ) : (
        <AgentEffectsSource
          value={{ ...value, prompt: value.prompt ?? "" }}
          label="Source film"
          description="Create a separate effects track for this film. Choose below how the new preview should use its original audio."
          disabled={disabled}
          onBusy={onBusy}
          onChange={(next) =>
            onChange({ ...value, ...next, prompt: value.prompt })
          }
        />
      )}
      <label>
        Original sound
        <select
          aria-label="Film sound mix"
          value={value.preview_mode ?? "mix"}
          disabled={disabled}
          onChange={(e) =>
            onChange({
              ...value,
              preview_mode: e.target.value as "mix" | "replace",
            })
          }
        >
          <option value="mix">Keep and mix with the new effects</option>
          <option value="replace">Replace audio in the new preview</option>
        </select>
      </label>
      {(value.preview_mode ?? "mix") === "mix" && (
        <details>
          <summary>Mix levels</summary>
          <label>
            Original sound · {Math.round((value.original_gain ?? 1) * 100)}%
            <input
              aria-label="Original film sound level"
              type="range"
              min={0}
              max={4}
              step={0.01}
              value={value.original_gain ?? 1}
              disabled={disabled}
              onChange={(e) =>
                onChange({ ...value, original_gain: Number(e.target.value) })
              }
            />
          </label>
          <label>
            New effects · {Math.round((value.effects_gain ?? 0.65) * 100)}%
            <input
              aria-label="New film effects level"
              type="range"
              min={0}
              max={4}
              step={0.01}
              value={value.effects_gain ?? 0.65}
              disabled={disabled}
              onChange={(e) =>
                onChange({ ...value, effects_gain: Number(e.target.value) })
              }
            />
          </label>
        </details>
      )}
      <p className="muted">
        The original film and a separate effects WAV stay in Library. A mixed
        result can be reopened in the film editor.
      </p>
    </section>
  );
}
