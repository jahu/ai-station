import { useQuery } from "@tanstack/react-query";
import { Clock3 } from "lucide-react";
import { api } from "../api";
import { Button } from "../components/ui/button";
import type { VideoCapabilities } from "../components/media/VideoMemoryProfile";
import type { AgentMediaScope } from "./agent-media";
import "./AgentVideoSetup.css";

type VideoScope = Extract<AgentMediaScope, { kind: "video" }>;
export type VideoSetupPatch = { media: VideoScope; maximum_runtime: number };

export default function AgentVideoSetup({
  value,
  maximumRuntime,
  disabled,
  onApply,
  actionLabel = "Use suggested setup",
  tabIndex,
}: {
  value?: AgentMediaScope | null;
  maximumRuntime: number;
  disabled?: boolean;
  onApply: (patch: VideoSetupPatch) => void;
  actionLabel?: string;
  tabIndex?: number;
}) {
  const capability = useQuery({
    queryKey: ["video-capabilities"],
    enabled: value?.kind === "video",
    queryFn: () => api<VideoCapabilities>("/video/capabilities"),
  });
  if (value?.kind !== "video" || !capability.data?.available) return null;
  const request = value.request;
  const suggestedLimit = request.duration_seconds <= 15 ? 7200 : 14400;
  const needsTime = maximumRuntime < suggestedLimit;
  const compatible =
    !request.image_artifact_id &&
    (request.width ?? 1280) === 1280 &&
    (request.height ?? 704) === 704 &&
    (request.steps ?? 20) >= 20;
  const needsMemory =
    compatible &&
    (request.memory_profile ?? "default") === "default" &&
    capability.data.recommended_memory_profile === "bounded_11g" &&
    capability.data.memory_profiles?.some(
      (profile) => profile.id === "bounded_11g" && profile.available,
    );
  if (!needsTime && !needsMemory) return null;
  const hours = suggestedLimit / 3600;
  return (
    <section className="agent-video-setup" aria-label="Suggested video setup">
      <h3>
        <Clock3 size={16} />
        Suggested video setup
      </h3>
      <p>
        Local video can take many minutes per segment.
        {needsTime
          ? ` Allow up to ${hours} hours for waiting, generation and assembly.`
          : " Keep your current time limit."}
        {needsMemory &&
          " The reduced-RAM landscape profile is recommended for currently available memory."}{" "}
        Generation finishes when the film is ready.
      </p>
      <Button
        type="button"
        disabled={disabled}
        tabIndex={tabIndex}
        onClick={() =>
          onApply({
            media: {
              ...value,
              request: {
                ...request,
                ...(needsMemory
                  ? { memory_profile: "bounded_11g" as const }
                  : {}),
              },
            },
            maximum_runtime: Math.max(maximumRuntime, suggestedLimit),
          })
        }
      >
        {actionLabel}
      </Button>
    </section>
  );
}
