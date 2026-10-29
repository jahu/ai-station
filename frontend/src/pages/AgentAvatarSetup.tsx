import { Clock3 } from "lucide-react";
import { Button } from "../components/ui/button";
import { useAvatarCapabilities } from "../components/media/AvatarMemoryProfile";
import type { AgentMediaScope } from "./agent-media";
import "./AgentVideoSetup.css";
import { useWholeAvatarCapabilities } from "../components/media/AvatarWholeProfile";
import { stableAvatarRequest } from "./agent-media";

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
  const whole = useWholeAvatarCapabilities(value?.kind === "avatar");
  if (
    value?.kind !== "avatar" ||
    (!capability.data?.available && !whole.data?.available)
  )
    return null;
  const request = value.request;
  const stable = !!request.generation_profile || whole.data?.available === true;
  const suggestedRuntime = stable ? 14400 : 7200;
  const needsQuality = stable && !request.generation_profile;
  const needsTime = maximumRuntime < suggestedRuntime;
  const needsMemory =
    !stable &&
    (request.size ?? 384) === 384 &&
    (request.steps ?? 8) >= 8 &&
    (request.memory_profile ?? "default") === "default" &&
    capability.data?.recommended_memory_profile === "bounded_11g" &&
    capability.data?.memory_profiles?.some(
      (profile) => profile.id === "bounded_11g" && profile.available,
    );
  if (!needsTime && !needsMemory && !needsQuality) return null;
  return (
    <section className="agent-video-setup" aria-label="Suggested avatar setup">
      <h3>
        <Clock3 size={16} /> Suggested avatar setup
      </h3>
      <p>
        {stable
          ? "Stable detail animates the whole recording with Sonic."
          : "Local avatars may need several rendering windows."}
        {needsTime
          ? ` Allow up to ${stable ? 4 : 2} hours for waiting, speech and the complete recording.`
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
              description_source:
                stable && request.speech_text === null
                  ? "fixed"
                  : value.description_source,
              request: {
                ...(stable ? stableAvatarRequest(request) : request),
                ...(needsMemory
                  ? { memory_profile: "bounded_11g" as const }
                  : {}),
              },
            },
            maximum_runtime: Math.max(maximumRuntime, suggestedRuntime),
          })
        }
      >
        {actionLabel}
      </Button>
    </section>
  );
}
