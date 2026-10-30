import { Link } from "react-router-dom";
import { Waves } from "lucide-react";
import type { Artifact } from "../../api";

export default function AddSoundLink({ artifact }: { artifact: Artifact }) {
  if (
    artifact.type !== "video" ||
    artifact.mime_type !== "video/mp4" ||
    artifact.trashed_at ||
    artifact.purge_run_id ||
    artifact.purged_at ||
    !artifact.metadata?.frames ||
    ![24, 25].includes(Number(artifact.metadata?.fps))
  )
    return null;
  return (
    <Link
      className="effects-add-sound"
      to={`/audio?mode=effects&input=${artifact.id}`}
      aria-label={`Add sound ${artifact.id.slice(0, 8)}`}
    >
      <Waves size={15} /> Add sound
    </Link>
  );
}
