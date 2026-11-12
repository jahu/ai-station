import type { StudioShot } from "./studio-material";

export default function StudioShotComposition({
  shot,
  index,
  hasMedia,
  video,
  onChange,
}: {
  shot: StudioShot;
  index: number;
  hasMedia: boolean;
  video: boolean;
  onChange: (value: Partial<StudioShot>) => void;
}) {
  return (
    <fieldset className="studio-shot-composition">
      <legend>Composition</legend>
      <div className="studio-shot-composition-grid">
        <label>
          Layout
          <select
            aria-label={`Shot ${index + 1} layout`}
            value={shot.layout}
            onChange={(e) => onChange({ layout: e.target.value })}
          >
            {hasMedia && <option value="full_bleed">Full visual</option>}
            <option value="title">Title and visual</option>
            <option value="split">Side by side</option>
            <option value="statement">Statement</option>
            {(shot.points.length > 0 || shot.layout === "steps") && (
              <option value="steps">Key points</option>
            )}
            <option value="quote">Quote</option>
            <option value="closing">Closing</option>
          </select>
        </label>
        {hasMedia && (
          <>
            <label>
              Image / video fit
              <select
                aria-label={`Shot ${index + 1} media fit`}
                value={shot.media_fit}
                onChange={(e) =>
                  onChange({
                    media_fit: e.target.value as StudioShot["media_fit"],
                  })
                }
              >
                <option value="contain">Show whole visual</option>
                <option value="cover">Fill panel · crop edges</option>
              </select>
            </label>
            <label>
              Visual movement
              <select
                aria-label={`Shot ${index + 1} visual movement`}
                value={shot.media_motion}
                onChange={(e) => onChange({ media_motion: e.target.value })}
              >
                <option value="auto">Automatic</option>
                <option value="hold">No added movement</option>
                <option value="push_in">Slow zoom in</option>
                <option value="pull_out">Slow zoom out</option>
                <option value="pan_left">Pan left</option>
                <option value="pan_right">Pan right</option>
                <option value="rise">Rise</option>
              </select>
            </label>
            {video && (
              <label>
                Start in source clip · seconds
                <input
                  aria-label={`Shot ${index + 1} clip start`}
                  type="number"
                  min={0}
                  max={600}
                  step="any"
                  required
                  value={shot.media_start_seconds}
                  onChange={(e) =>
                    onChange({ media_start_seconds: Number(e.target.value) })
                  }
                />
              </label>
            )}
          </>
        )}
      </div>
      {hasMedia && (
        <p>
          Keep diagrams and edge details intact with Show whole visual and no
          added movement. Zooming and panning can crop edges. These settings
          change the edit; the source file stays untouched.
          {video && " The complete scene must fit within the source clip."}
        </p>
      )}
    </fieldset>
  );
}
