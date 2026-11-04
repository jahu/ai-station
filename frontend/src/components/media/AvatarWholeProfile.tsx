import { useQuery } from "@tanstack/react-query";
import { Sparkles, ShieldCheck, Clock3 } from "lucide-react";
import { api } from "../../api";
import "./AvatarWholeProfile.css";

export const WHOLE_AVATAR_PROFILE = "sonic_whole_768_v1" as const;
export type AvatarGenerationProfile = typeof WHOLE_AVATAR_PROFILE;
type WholeCapabilities = {
  available: boolean;
  backend?: string;
  readiness?: "disabled" | "checking" | "unavailable" | "ready";
  reason?: string;
  detected_gpu_count?: number;
  configuration_source?: "managed" | "configured";
  eligible_gpu_indices?: number[];
};

export function useWholeAvatarCapabilities(enabled = true) {
  return useQuery({
    queryKey: ["whole-avatar-capabilities"],
    enabled,
    queryFn: async (): Promise<WholeCapabilities> => {
      const result = await api<WholeCapabilities | undefined>(
        "/avatars/whole-capabilities",
      );
      // Older native installations retain their explicit Echo availability.
      return result?.backend === "sonic"
        ? result
        : { available: false, readiness: "disabled" };
    },
    refetchInterval: (query) =>
      query.state.data?.readiness === "checking" ? 2000 : false,
  });
}

export default function AvatarWholeProfile({
  checking = false,
}: {
  checking?: boolean;
}) {
  return (
    <section
      className="avatar-whole-profile"
      aria-label="High-detail avatar quality"
    >
      <div className="avatar-whole-heading">
        <span className="avatar-whole-icon">
          <Sparkles size={19} />
        </span>
        <div>
          <strong>Stable detail</strong>
          <span>Sonic · Local</span>
        </div>
        <span className="avatar-whole-tag">Up to 768 px</span>
      </div>
      <p>
        The entire recording is animated together for consistent facial details
        and natural movement.
      </p>
      <div className="avatar-whole-facts">
        <span>
          <ShieldCheck size={14} /> Portrait proportions preserved
        </span>
        <span>25 fps · full speech</span>
      </div>
      <p className="avatar-whole-time">
        <Clock3 size={14} />{" "}
        {checking
          ? "Checking the installed model files…"
          : "Detailed local rendering can take hours. Your progress is saved while you use other workspaces."}
      </p>
    </section>
  );
}
