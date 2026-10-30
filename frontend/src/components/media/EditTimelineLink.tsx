import { Clapperboard } from "lucide-react";
import { Link } from "react-router-dom";
import type { Artifact } from "../../api";

export default function EditTimelineLink({ artifact }: { artifact: Artifact }) {
  if (
    artifact.trashed_at ||
    artifact.purge_run_id ||
    artifact.purged_at ||
    !["video/mp4", "audio/wav"].includes(artifact.mime_type) ||
    (artifact.mime_type === "video/mp4" &&
      (!artifact.run_id ||
        !artifact.metadata?.frames ||
        ![24, 25].includes(Number(artifact.metadata?.fps))))
  )
    return null;
  return (
    <Link
      className="effects-add-sound"
      to={`/video?mode=edit&input=${artifact.id}`}
      aria-label={`Edit on timeline ${artifact.id.slice(0, 8)}`}
    >
      <Clapperboard size={14} /> Edit on timeline
    </Link>
  );
}
