import { useQuery } from "@tanstack/react-query";
import { api } from "../../api";

export type VideoProfile = "default" | "bounded_11g";

export default function VideoMemoryProfile({
  value,
  onChange,
  disabled,
}: {
  value: VideoProfile;
  onChange: (value: VideoProfile) => void;
  disabled?: boolean;
}) {
  const capability = useQuery({
    queryKey: ["video-capabilities"],
    queryFn: () =>
      api<{
        available: boolean;
        memory_profiles?: { id: string; available: boolean }[];
      }>("/video/capabilities"),
  });
  const ready =
    capability.data?.available &&
    capability.data.memory_profiles?.some(
      (profile) => profile.id === "bounded_11g" && profile.available,
    );
  if (!ready && value === "default") return null;
  return (
    <label>
      Generation profile
      <select
        aria-label="Video generation profile"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value as VideoProfile)}
      >
        <option value="default">Standard</option>
        <option value="bounded_11g" disabled={!ready}>
          Reduced RAM · landscape
        </option>
      </select>
      <small className="muted">
        {value === "bounded_11g"
          ? ready
            ? "Limits system RAM to 11 GB without swap. Uses 1280 × 704 and at least 20 steps; generation may take longer."
            : "This saved profile is currently unavailable. Choose Standard or check the video runtime."
          : "Use Reduced RAM when other applications leave less memory for video."}
      </small>
    </label>
  );
}
