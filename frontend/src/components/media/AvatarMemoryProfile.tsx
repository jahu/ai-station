import { useQuery } from "@tanstack/react-query";
import { api } from "../../api";

export type AvatarProfile = "default" | "bounded_11g";
export type AvatarCapabilities = {
  available: boolean;
  recommended_memory_profile?: AvatarProfile;
  memory_profiles?: { id: string; available: boolean }[];
};

export function useAvatarCapabilities(enabled = true) {
  return useQuery({
    queryKey: ["avatar-capabilities"],
    enabled,
    queryFn: () => api<AvatarCapabilities>("/avatars/capabilities"),
  });
}

export default function AvatarMemoryProfile({
  value,
  onChange,
  disabled,
  supported = true,
  recommended,
}: {
  value: AvatarProfile;
  onChange: (value: AvatarProfile) => void;
  disabled?: boolean;
  supported?: boolean;
  recommended?: boolean;
}) {
  const capability = useAvatarCapabilities();
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
        aria-label="Avatar generation profile"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value as AvatarProfile)}
      >
        <option value="default">Standard</option>
        <option value="bounded_11g" disabled={!ready || !supported}>
          Reduced RAM · full precision
        </option>
      </select>
      <small className="muted">
        {recommended &&
          ready &&
          value === "bounded_11g" &&
          "Selected for the currently available memory. "}
        {value === "bounded_11g"
          ? !ready
            ? "This saved profile is unavailable. Choose Standard or check the avatar runtime."
            : !supported
              ? "Use 384 × 384 with at least 8 steps, or choose Standard for these settings."
              : "Keeps full model precision at 384 × 384 with at least 8 steps. Limits system RAM to 11 GB without swap; generation may take longer."
          : "Use Reduced RAM at 384 × 384 when other applications leave less memory."}
      </small>
    </label>
  );
}
