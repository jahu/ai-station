import { useQuery } from "@tanstack/react-query";
import { api } from "../../api";

export type VideoProfile = "default" | "bounded_11g";
export type VideoCapabilities = {
  available: boolean;
  reason?: string;
  configuration_source?: "managed" | "configured";
  eligible_gpu_indices?: number[];
  recommended_memory_profile?: VideoProfile;
  memory_profiles?: { id: string; available: boolean }[];
};

export default function VideoMemoryProfile({
  value,
  onChange,
  disabled,
  recommended,
}: {
  value: VideoProfile;
  onChange: (value: VideoProfile) => void;
  disabled?: boolean;
  recommended?: boolean;
}) {
  const capability = useQuery({
    queryKey: ["video-capabilities"],
    queryFn: () => api<VideoCapabilities>("/video/capabilities"),
  });
  const ready =
    capability.data?.available &&
    capability.data.memory_profiles?.some(
      (profile) => profile.id === "bounded_11g" && profile.available,
    );
  if (capability.data?.configuration_source === "managed")
    return (
      <div className="notice">
        <strong>Installed video profile</strong>
        <p>
          1280 × 704 · at least 20 steps · 11 GiB system RAM without swap.
          Clips, image animation and longer films use the same local engine.
        </p>
      </div>
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
        {recommended &&
          ready &&
          value === "bounded_11g" &&
          "Selected for the currently available memory. "}
        {value === "bounded_11g"
          ? ready
            ? "Limits system RAM to 11 GB without swap. Uses 1280 × 704 and at least 20 steps; generation may take longer."
            : "This saved profile is currently unavailable. Choose Standard or check the video runtime."
          : "Use Reduced RAM when other applications leave less memory for video."}
      </small>
    </label>
  );
}
