import { Settings2 } from "lucide-react";
import MediaInput from "../components/media/MediaInput";
import AvatarMemoryProfile from "../components/media/AvatarMemoryProfile";
import { useHardware } from "../api";
import { GpuTargetChoiceList } from "./GpuTargetChoiceList";
import type { AvatarMediaRequest } from "./agent-media";
import { stableAvatarRequest } from "./agent-media";
import AvatarWholeProfile, {
  useWholeAvatarCapabilities,
} from "../components/media/AvatarWholeProfile";

export default function AgentAvatarScope({
  value,
  onChange,
  disabled,
  onBusy,
}: {
  value: AvatarMediaRequest;
  onChange: (value: AvatarMediaRequest) => void;
  disabled: boolean;
  onBusy: (busy: boolean) => void;
}) {
  const hardware = useHardware();
  const whole = useWholeAvatarCapabilities();
  const stable = !!value.generation_profile;
  const generated = value.speech_text !== null;
  const patch = (change: Partial<AvatarMediaRequest>) =>
    onChange({ ...value, ...change });
  return (
    <div className="agent-avatar-settings">
      {(whole.data?.available ||
        stable ||
        whole.data?.readiness === "checking") && (
        <label>
          Avatar quality
          <select
            aria-label="Agent avatar quality"
            value={stable ? "stable" : "legacy"}
            disabled={disabled}
            onChange={(event) => {
              if (event.target.value === "stable")
                onChange(stableAvatarRequest(value));
              else {
                const request = { ...value };
                delete request.generation_profile;
                onChange(request);
              }
            }}
          >
            <option value="stable" disabled={!whole.data?.available}>
              Stable detail · Sonic
            </option>
            <option value="legacy">EchoMimic · legacy settings</option>
          </select>
        </label>
      )}
      {stable && (
        <AvatarWholeProfile checking={whole.data?.readiness === "checking"} />
      )}
      {stable && !whole.isPending && !whole.data?.available && (
        <p className="muted" role="status">
          {whole.data?.reason ||
            "Stable detail is unavailable. Inspect Avatars setup before running this agent."}
        </p>
      )}
      <p className="muted">
        {generated
          ? "Your portrait and voice stay fixed. Goal mode writes fresh Polish words from the goal and reviewed sources; fixed mode speaks the exact text above."
          : stable
            ? "Uses your entire saved recording with natural movement."
            : "Uses your entire saved recording. Goal mode can prepare motion direction; it does not change the recorded words."}{" "}
        The full speech is animated, up to 60 seconds. Allow enough runtime for
        your chosen quality.
      </p>
      <MediaInput
        kind="image"
        label="Avatar portrait"
        hint="Choose a PNG/JPEG portrait from Library or upload one."
        value={value.image_artifact_id ?? ""}
        disabled={disabled}
        onBusy={onBusy}
        onChange={(id) => patch({ image_artifact_id: id || null })}
      />
      <MediaInput
        kind="audio"
        label={generated ? "Avatar voice reference" : "Avatar recording"}
        hint={
          generated
            ? "Choose a clear PCM WAV voice reference, 0.1–60 seconds."
            : "Choose a PCM WAV recording, 0.68–60 seconds. The whole recording will be used."
        }
        value={value.audio_artifact_id ?? ""}
        disabled={disabled}
        onBusy={onBusy}
        onChange={(id) => patch({ audio_artifact_id: id || null })}
      />
      <details>
        <summary>
          <Settings2 size={15} />
          Advanced avatar settings
        </summary>
        {!stable && (
          <AvatarMemoryProfile
            value={value.memory_profile ?? "default"}
            onChange={(memory_profile) => patch({ memory_profile })}
            disabled={disabled}
            supported={(value.size ?? 384) === 384 && (value.steps ?? 8) >= 8}
          />
        )}
        {generated && !stable && (
          <label>
            Motion direction
            <textarea
              aria-label="Avatar motion direction"
              value={value.prompt}
              maxLength={2000}
              onChange={(event) => patch({ prompt: event.target.value })}
            />
          </label>
        )}
        <div className="agent-fields">
          {!stable && (
            <label>
              Canvas size
              <select
                aria-label="Agent avatar size"
                value={value.size ?? 384}
                onChange={(event) =>
                  patch({ size: Number(event.target.value) as 256 | 384 | 512 })
                }
              >
                <option value={256}>Draft · 256 × 256</option>
                <option value={384}>384 × 384</option>
                <option value={512}>512 × 512</option>
              </select>
            </label>
          )}
          {!stable && (
            <label>
              Steps
              <input
                type="number"
                min={4}
                max={30}
                aria-label="Agent avatar steps"
                value={value.steps ?? 8}
                onChange={(event) =>
                  patch({ steps: Number(event.target.value) })
                }
              />
            </label>
          )}
          <label>
            Seed
            <input
              type="number"
              min={0}
              max={2147483647}
              aria-label="Agent avatar seed"
              value={value.seed ?? 43}
              onChange={(event) => patch({ seed: Number(event.target.value) })}
            />
          </label>
        </div>
        <GpuTargetChoiceList
          value={value.gpu ?? "auto"}
          gpus={hardware.data?.gpus ?? []}
          onChange={(gpu) => patch({ gpu })}
        />
      </details>
    </div>
  );
}
