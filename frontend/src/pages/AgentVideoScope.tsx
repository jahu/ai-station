import { useState } from "react";
import { Settings2 } from "lucide-react";
import MediaInput from "../components/media/MediaInput";
import VideoSceneEditor from "../components/media/VideoSceneEditor";
import {
  scenePlanError,
  type SceneDraft,
} from "../components/media/video-scenes";
import { randomId } from "../lib/random-id";
import { useHardware } from "../api";
import { GpuTargetChoiceList } from "./GpuTargetChoiceList";
import type { VideoMediaRequest } from "./agent-media";

export default function AgentVideoScope({
  value,
  onChange,
  disabled,
  onBusy,
}: {
  value: VideoMediaRequest;
  onChange: (value: VideoMediaRequest) => void;
  disabled: boolean;
  onBusy: (busy: boolean) => void;
}) {
  const hardware = useHardware();
  const incoming = value.scenes;
  const [sceneState, setSceneState] = useState(() => ({
    source: incoming,
    rows: (incoming ?? []).map((scene) => ({ ...scene, key: randomId() })),
  }));
  if (sceneState.source !== incoming)
    setSceneState({
      source: incoming,
      rows: (incoming ?? []).map((scene) => ({ ...scene, key: randomId() })),
    });
  function scenesChanged(rows: SceneDraft[]) {
    const source = rows.map(({ prompt, duration_seconds }) => ({
      prompt,
      duration_seconds,
    }));
    setSceneState({ source, rows });
    onChange({
      ...value,
      scenes: source,
      duration_seconds: source.reduce(
        (sum, scene) => sum + scene.duration_seconds,
        0,
      ),
    });
  }
  const patch = (change: Partial<VideoMediaRequest>) =>
    onChange({ ...value, ...change });
  return (
    <div className="agent-video-settings">
      <p className="muted">
        One complete film, up to 60 seconds. Segments are generated locally and
        assembled automatically. Goal mode changes the shared direction; your
        length, shots and first frame stay fixed. Allow enough time in the
        agent's runtime budget for the chosen quality.
      </p>
      <div className="form-grid">
        <label>
          Film length (seconds)
          <input
            aria-label="Agent film length"
            type="number"
            min={1}
            max={60}
            step={1}
            value={value.duration_seconds}
            disabled={!!incoming?.length}
            onChange={(e) =>
              patch({ duration_seconds: Number(e.target.value) })
            }
          />
        </label>
        <label>
          Motion
          <select
            aria-label="Agent video motion"
            value={value.composition_mode}
            onChange={(e) =>
              patch({
                composition_mode: e.target.value as "continuous" | "shots",
                scenes: null,
              })
            }
          >
            <option value="continuous">Continuous motion</option>
            <option value="shots">Sequence of shots</option>
          </select>
        </label>
      </div>
      {value.composition_mode === "shots" && (
        <>
          <label className="check-row">
            <input
              type="checkbox"
              checked={incoming != null}
              onChange={(e) => {
                if (e.target.checked)
                  scenesChanged([
                    {
                      key: randomId(),
                      prompt: "",
                      duration_seconds: value.duration_seconds,
                    },
                  ]);
                else patch({ scenes: null });
              }}
            />
            Plan individual scenes
          </label>
          {incoming != null && (
            <VideoSceneEditor
              scenes={sceneState.rows}
              onChange={scenesChanged}
              error={scenePlanError(value.prompt, sceneState.rows)}
            />
          )}
        </>
      )}
      <MediaInput
        kind="image"
        label="First frame (optional)"
        hint="Choose a PNG/JPEG image, or leave empty to create the film from text."
        value={value.image_artifact_id ?? ""}
        disabled={disabled}
        onBusy={onBusy}
        onChange={(id) => patch({ image_artifact_id: id || null })}
      />
      <details>
        <summary>
          <Settings2 size={15} />
          Advanced video settings
        </summary>
        <div className="form-grid">
          <label>
            Resolution
            <select
              aria-label="Agent video resolution"
              value={`${value.width ?? 1280}x${value.height ?? 704}`}
              onChange={(e) => {
                const [width, height] = e.target.value.split("x").map(Number);
                patch({ width, height });
              }}
            >
              {![
                ["1280", "704"],
                ["704", "1280"],
                ["768", "768"],
                ["512", "288"],
              ].some(
                ([w, h]) =>
                  Number(w) === (value.width ?? 1280) &&
                  Number(h) === (value.height ?? 704),
              ) && (
                <option value={`${value.width}x${value.height}`}>
                  {value.width} × {value.height}
                </option>
              )}
              <option value="1280x704">Landscape · 1280 × 704</option>
              <option value="704x1280">Portrait · 704 × 1280</option>
              <option value="768x768">Square · 768 × 768</option>
              <option value="512x288">Draft · 512 × 288</option>
            </select>
          </label>
          <label>
            Steps
            <input
              type="number"
              min={4}
              max={40}
              aria-label="Agent video steps"
              value={value.steps ?? 20}
              onChange={(e) => patch({ steps: Number(e.target.value) })}
            />
          </label>
          <label>
            Seed
            <input
              type="number"
              min={0}
              max={2147483647}
              aria-label="Agent video seed"
              value={value.seed ?? 43}
              onChange={(e) => patch({ seed: Number(e.target.value) })}
            />
          </label>
          <label>
            CFG
            <input
              type="number"
              min={1}
              max={10}
              step={0.1}
              aria-label="Agent video CFG"
              value={value.cfg ?? 5}
              onChange={(e) => patch({ cfg: Number(e.target.value) })}
            />
          </label>
        </div>
        <label>
          Negative prompt
          <textarea
            aria-label="Agent video negative prompt"
            maxLength={2000}
            value={value.negative_prompt ?? ""}
            onChange={(e) => patch({ negative_prompt: e.target.value })}
          />
        </label>
        <GpuTargetChoiceList
          value={value.gpu ?? "auto"}
          gpus={hardware.data?.gpus ?? []}
          onChange={(gpu) => patch({ gpu })}
        />
      </details>
    </div>
  );
}
