import { useRef } from "react";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { Button } from "../ui/button";

export type SceneDraft = {
  key: string;
  prompt: string;
  duration_seconds: number;
};

export function scenePlanError(shared: string, scenes: SceneDraft[]) {
  if (!scenes.length || scenes.some((scene) => !scene.prompt.trim()))
    return "Describe every scene before generating.";
  if (
    scenes.some(
      (scene) =>
        !Number.isInteger(scene.duration_seconds) ||
        scene.duration_seconds < 1 ||
        scene.duration_seconds > 60,
    )
  )
    return "Each scene needs a duration from 1 to 60 whole seconds.";
  if (scenes.reduce((total, scene) => total + scene.duration_seconds, 0) > 60)
    return "The complete film can be up to 60 seconds.";
  if (
    scenes.some(
      (scene) => shared.trim().length + 2 + scene.prompt.trim().length > 2000,
    )
  )
    return "Shared instructions and each scene must fit 2000 characters together.";
  return "";
}

export default function VideoSceneEditor({
  scenes,
  onChange,
  error,
}: {
  scenes: SceneDraft[];
  onChange: (scenes: SceneDraft[]) => void;
  error: string;
}) {
  const fields = useRef(new Map<string, HTMLTextAreaElement>());
  const focus = (key: string) =>
    window.setTimeout(() => fields.current.get(key)?.focus(), 0);
  const update = (index: number, change: Partial<SceneDraft>) =>
    onChange(
      scenes.map((scene, at) =>
        at === index ? { ...scene, ...change } : scene,
      ),
    );
  const move = (index: number, delta: number) => {
    const next = [...scenes];
    [next[index], next[index + delta]] = [next[index + delta], next[index]];
    onChange(next);
  };
  return (
    <section className="video-scene-editor" aria-label="Scene plan">
      <div className="row spread">
        <h3>Your scene plan</h3>
        <span className="muted">{scenes.length} / 20 scenes</span>
      </div>
      <p className="muted">
        Scenes share the instructions above and are joined with cuts.
      </p>
      <ol className="video-scene-cards">
        {scenes.map((scene, index) => (
          <li key={scene.key}>
            <div className="row spread">
              <strong>Scene {index + 1}</strong>
              <div className="row video-scene-actions">
                <Button
                  type="button"
                  variant="ghost"
                  disabled={index === 0}
                  aria-label={`Move scene ${index + 1} earlier`}
                  onClick={() => move(index, -1)}
                >
                  <ArrowUp size={14} />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  disabled={index === scenes.length - 1}
                  aria-label={`Move scene ${index + 1} later`}
                  onClick={() => move(index, 1)}
                >
                  <ArrowDown size={14} />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  disabled={scenes.length === 1}
                  aria-label={`Remove scene ${index + 1}`}
                  onClick={() => {
                    onChange(scenes.filter((_, at) => at !== index));
                    focus(scenes[index + 1]?.key ?? scenes[index - 1].key);
                  }}
                >
                  <Trash2 size={14} />
                </Button>
              </div>
            </div>
            <label>
              <span className="sr-only">Scene {index + 1} prompt</span>
              <textarea
                ref={(field) => {
                  if (field) fields.current.set(scene.key, field);
                  else fields.current.delete(scene.key);
                }}
                rows={3}
                maxLength={1000}
                value={scene.prompt}
                onChange={(event) =>
                  update(index, { prompt: event.target.value })
                }
                placeholder={
                  index === 0
                    ? "An opening wide shot of the forest at dawn…"
                    : "Describe what happens next…"
                }
              />
            </label>
            <label className="video-scene-duration">
              Duration{" "}
              <span>
                <input
                  aria-label={`Scene ${index + 1} duration`}
                  type="number"
                  min={1}
                  max={60}
                  step={1}
                  value={scene.duration_seconds}
                  onChange={(event) =>
                    update(index, {
                      duration_seconds: Number(event.target.value),
                    })
                  }
                />{" "}
                seconds
              </span>
            </label>
          </li>
        ))}
      </ol>
      <Button
        type="button"
        variant="secondary"
        disabled={scenes.length >= 20}
        onClick={() => {
          const scene = {
            key: crypto.randomUUID(),
            prompt: "",
            duration_seconds: 5,
          };
          onChange([...scenes, scene]);
          focus(scene.key);
        }}
      >
        <Plus size={15} />
        Add scene
      </Button>
      {error && (
        <p className="notice" role="status">
          {error}
        </p>
      )}
    </section>
  );
}
