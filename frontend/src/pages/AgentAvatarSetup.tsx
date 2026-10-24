import { Clock3 } from "lucide-react";
import { Button } from "../components/ui/button";
import { useAvatarCapabilities } from "../components/media/AvatarMemoryProfile";
import type { AgentMediaScope } from "./agent-media";
import "./AgentVideoSetup.css";

type AvatarScope = Extract<AgentMediaScope, { kind: "avatar" }>;
export type AvatarSetupPatch = { media: AvatarScope; maximum_runtime: number };

export default function AgentAvatarSetup({
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
  onApply: (patch: AvatarSetupPatch) => void;
  actionLabel?: string;
  tabIndex?: number;
}) {
  const capability = useAvatarCapabilities(value?.kind === "avatar");
  if (value?.kind !== "avatar" || !capability.data?.available) return null;
  const request = value.request;
  const needsTime = maximumRuntime < 7200;
  const needsMemory =
    (request.size ?? 384) === 384 &&
    (request.steps ?? 8) >= 8 &&
    (request.memory_profile ?? "default") === "default" &&
    capability.data.recommended_memory_profile === "bounded_11g" &&
    capability.data.memory_profiles?.some(
      (profile) => profile.id === "bounded_11g" && profile.available,
    );
  if (!needsTime && !needsMemory) return null;
  return (
    <section className="agent-video-setup" aria-label="Suggested avatar setup">
      <h3>
        <Clock3 size={16} /> Suggested avatar setup
      </h3>
      <p>
        Local avatars may need several rendering windows.
        {needsTime
          ? " Allow up to 2 hours for waiting, speech, animation and assembly."
          : " Keep your current time limit."}
        {needsMemory &&
          " The reduced-RAM profile keeps full model precision and is recommended for currently available memory."}{" "}
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
            maximum_runtime: Math.max(maximumRuntime, 7200),
          })
        }
      >
        {actionLabel}
      </Button>
    </section>
  );
}
