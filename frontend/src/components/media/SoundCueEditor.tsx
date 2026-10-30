import { Plus, Trash2 } from "lucide-react";
import { Button } from "../ui/button";

import { cuesValid, type SoundCue } from "./sound-cues";

export default function SoundCueEditor({
  value,
  onChange,
  fps,
  frames,
  disabled,
}: {
  value: SoundCue[];
  onChange: (value: SoundCue[]) => void;
  fps: number;
  frames: number;
  disabled: boolean;
}) {
  if (![24, 25].includes(fps) || !Number.isInteger(frames) || frames < 1)
    return null;
  const seconds = (frame: number) => Number((frame / fps).toFixed(3));
  const next = value.at(-1)?.end_frame ?? 0;
  function change(index: number, patch: Partial<SoundCue>) {
    onChange(value.map((cue, i) => (i === index ? { ...cue, ...patch } : cue)));
  }
  return (
    <details className="effects-cues">
      <summary>
        Change sounds over time{" "}
        {value.length > 0 && <span>· {value.length}</span>}
      </summary>
      <p className="muted">
        Add scene directions where the sound changes. The overall description
        applies elsewhere. Times snap to the film’s frames; scenes must be
        ordered and cannot overlap.
      </p>
      {value.map((cue, index) => (
        <section
          className="effects-cue"
          role="group"
          aria-label={`Sound cue ${index + 1}`}
          key={index}
        >
          <div className="effects-cue-heading">
            <strong>Scene {index + 1}</strong>
            <Button
              type="button"
              variant="ghost"
              disabled={disabled}
              aria-label={`Remove sound cue ${index + 1}`}
              onClick={() => onChange(value.filter((_, i) => i !== index))}
            >
              <Trash2 size={14} /> Remove
            </Button>
          </div>
          <div className="effects-cue-times">
            <label>
              From (seconds)
              <input
                aria-label={`Scene ${index + 1} start in seconds`}
                type="number"
                min={0}
                max={seconds(frames)}
                step="any"
                value={seconds(cue.start_frame)}
                disabled={disabled}
                onChange={(e) =>
                  change(index, {
                    start_frame: Math.round(Number(e.target.value) * fps),
                  })
                }
              />
            </label>
            <label>
              To (seconds)
              <input
                aria-label={`Scene ${index + 1} end in seconds`}
                type="number"
                min={1 / fps}
                max={seconds(frames)}
                step="any"
                value={seconds(cue.end_frame)}
                disabled={disabled}
                onChange={(e) =>
                  change(index, {
                    end_frame: Math.round(Number(e.target.value) * fps),
                  })
                }
              />
            </label>
          </div>
          <label>
            What should we hear in this scene?
            <textarea
              aria-label={`Scene ${index + 1} sound description`}
              rows={3}
              maxLength={500}
              value={cue.prompt}
              disabled={disabled}
              onChange={(e) => change(index, { prompt: e.target.value })}
              placeholder="A bicycle bell rings, followed by wheels on gravel…"
            />
          </label>
        </section>
      ))}
      {value.length > 0 && !cuesValid(value, frames) && (
        <p role="alert">
          Give each scene a description and a valid, non-overlapping time range
          inside the film.
        </p>
      )}
      <Button
        type="button"
        variant="secondary"
        disabled={disabled || value.length >= 16 || next >= frames}
        onClick={() =>
          onChange([
            ...value,
            {
              start_frame: next,
              end_frame: Math.min(frames, next + fps * 4),
              prompt: "",
            },
          ])
        }
      >
        <Plus size={14} /> Add scene direction
      </Button>
    </details>
  );
}
