import { Link } from "react-router-dom";
import { UserRound, X } from "lucide-react";
import type { Artifact } from "../api";
import LibraryPicker from "../components/media/LibraryPicker";
import { Button } from "../components/ui/button";

export type PresenterPlacement = "auto" | "right" | "bottom";

export default function StudioPresenter({
  clip,
  placement,
  seconds,
  busy,
  onClip,
  onPlacement,
}: {
  clip: Artifact | null;
  placement: PresenterPlacement;
  seconds: number;
  busy: boolean;
  onClip: (clip: Artifact | null) => void;
  onPlacement: (placement: PresenterPlacement) => void;
}) {
  return (
    <details className="studio-presenter" open={!!clip || undefined}>
      <summary>
        <UserRound size={17} /> Add a presenter <span>Optional</span>
      </summary>
      <p className="studio-direction-note">
        Place an avatar or presenter beside your story. Choose a clip of at
        least {seconds.toFixed(1)} seconds, speaking the same narration as your
        film. Your film soundtrack is kept; the clip’s audio is muted.
      </p>
      <LibraryPicker
        kind="video"
        existing={clip ? [clip.id] : []}
        limit={1}
        busy={busy}
        onSelect={(items) => onClip(items[0] ?? null)}
      />
      {clip && (
        <div className="studio-presenter-choice">
          <video
            controls
            playsInline
            muted
            preload="metadata"
            src={`/api/artifacts/${clip.id}/file`}
            aria-label="Selected presenter clip"
          />
          <div>
            <Link to={`/library/${clip.id}`}>
              {clip.title || clip.original_filename} ↗
            </Link>
            <label>
              Presenter position
              <select
                value={placement}
                disabled={busy}
                onChange={(event) =>
                  onPlacement(event.target.value as PresenterPlacement)
                }
              >
                <option value="auto">Automatic · fits your film format</option>
                <option value="right">Beside the story</option>
                <option value="bottom">Below the story</option>
              </select>
            </label>
            <p className="studio-direction-note">
              Your story is resized to leave room for the presenter.
            </p>
            <Button
              type="button"
              variant="ghost"
              disabled={busy}
              onClick={() => onClip(null)}
            >
              <X size={15} /> Remove presenter
            </Button>
          </div>
        </div>
      )}
    </details>
  );
}
