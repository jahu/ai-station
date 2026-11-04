import { useEffect, useRef, useState } from "react";
import { Film } from "lucide-react";

// A still from the actual film works for existing outputs too. Decode only
// visible cards, without playback, audio, inference or a bulk video download.
export default function ArtifactThumbnail({
  id,
  kind,
}: {
  id: string;
  kind: "image" | "video";
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const [visible, setVisible] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (kind !== "video" || !ref.current) return;
    if (typeof IntersectionObserver === "undefined") {
      // Metadata preloading is still bounded by the browser in older clients.
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: "100px" },
    );
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, [kind]);
  if (kind === "image")
    return <img loading="lazy" src={`/api/artifacts/${id}/thumbnail`} alt="" />;
  return (
    <span ref={ref} className="artifact-video-thumbnail" aria-hidden="true">
      <Film size={30} className="artifact-video-fallback" />
      {!failed && (visible || typeof IntersectionObserver === "undefined") && (
        <video
          src={`/api/artifacts/${id}/file`}
          preload="metadata"
          muted
          playsInline
          tabIndex={-1}
          disablePictureInPicture
          onLoadedMetadata={(event) => {
            const video = event.currentTarget;
            if (Number.isFinite(video.duration) && video.duration > 0)
              video.currentTime = Math.min(1, video.duration / 2);
          }}
          onError={() => setFailed(true)}
        />
      )}
    </span>
  );
}
