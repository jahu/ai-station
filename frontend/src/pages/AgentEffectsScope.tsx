import { useQuery } from "@tanstack/react-query";
import { api, useHardware, type Artifact } from "../api";
import MediaInput from "../components/media/MediaInput";
import SoundCueEditor from "../components/media/SoundCueEditor";
import type { EffectsMediaRequest } from "./agent-media";
import { GpuTargetChoiceList } from "./GpuTargetChoiceList";
import "./SoundEffects.css";

export default function AgentEffectsScope({
  value,
  onChange,
  disabled,
  onBusy,
}: {
  value: EffectsMediaRequest;
  onChange: (request: EffectsMediaRequest) => void;
  disabled: boolean;
  onBusy: (busy: boolean) => void;
}) {
  const hardware = useHardware();
  const source = useQuery({
    queryKey: ["artifact", value.video_artifact_id],
    queryFn: () => api<Artifact>(`/artifacts/${value.video_artifact_id}`),
    enabled: !!value.video_artifact_id,
  });
  const fps = Number(source.data?.metadata?.fps),
    frames = Number(source.data?.metadata?.frames);
  return (
    <div className="agent-video-settings">
      <p className="muted">
        Create an effects and ambience track for this film. The original stays
        in Library; a separate WAV and synchronized preview are saved each run.
        The preview plays the new effects track. Use Video → Edit a film to mix
        it with original speech or music.
      </p>
      <MediaInput
        kind="video"
        label="Agent source film"
        hint="Choose an inspected film from Library · up to 5 minutes. Changing the film clears scene timings."
        value={value.video_artifact_id ?? ""}
        onChange={(video_artifact_id) =>
          onChange({
            ...value,
            video_artifact_id: video_artifact_id || null,
            cues: [],
          })
        }
        disabled={disabled}
        onBusy={onBusy}
      />
      {source.data && (
        <SoundCueEditor
          value={value.cues ?? []}
          fps={fps}
          frames={frames}
          onChange={(cues) => onChange({ ...value, cues })}
          disabled={disabled}
        />
      )}
      <details>
        <summary>Advanced sound settings</summary>
        <label>
          Sounds to avoid
          <input
            value={value.negative_prompt ?? "speech, music"}
            maxLength={2000}
            onChange={(e) =>
              onChange({ ...value, negative_prompt: e.target.value })
            }
          />
        </label>
        <label>
          Sampling steps
          <input
            type="number"
            min={10}
            max={50}
            step={1}
            value={value.steps ?? 25}
            onChange={(e) =>
              onChange({ ...value, steps: Number(e.target.value) })
            }
          />
        </label>
        <label>GPU</label>
        <GpuTargetChoiceList
          value={value.gpu ?? "auto"}
          gpus={hardware.data?.gpus ?? []}
          onChange={(gpu) => onChange({ ...value, gpu })}
        />
        <p className="muted">
          Runs automatically select an available GPU. Saved film, scene timings
          and generation settings stay fixed when the agent writes a fresh
          overall description.
        </p>
      </details>
    </div>
  );
}
