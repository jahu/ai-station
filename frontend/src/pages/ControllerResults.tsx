import { useId, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ChevronDown } from "lucide-react";
import type { Artifact } from "../api";
import { Button } from "../components/ui/button";
import type { ActionResult, AssistantOptions } from "./AssistantActions";

const TERMINAL = new Set(["succeeded", "failed", "canceled", "interrupted"]);
const SOURCE_TOOLS = new Set([
  "web.search",
  "web.read",
  "web.image_search",
  "web.image_import",
  "artifact.read",
  "image.describe",
  "chat.reply",
  "system.inspect",
]);

function deliverables(result: ActionResult) {
  const seen = new Set<string>();
  return (result.controller_steps ?? [])
    .filter(
      (step) => step.status === "succeeded" && !SOURCE_TOOLS.has(step.tool),
    )
    .flatMap((step) =>
      (step.result.artifacts ?? []).map((artifact) => ({
        artifact,
        studio: step.result.studio_material_id
          ? {
              id: step.result.studio_material_id,
              revision: step.result.studio_revision_id,
            }
          : null,
      })),
    )
    .filter(({ artifact }) => {
      if (
        seen.has(artifact.id) ||
        artifact.trashed_at ||
        artifact.purged_at ||
        artifact.purge_run_id ||
        artifact.type === "log" ||
        artifact.metadata?.reference_only === true ||
        artifact.metadata?.internal_media === true ||
        artifact.metadata?.song_preparation === true ||
        artifact.metadata?.operation === "image.describe" ||
        ["pending", "rejected"].includes(
          String(
            (artifact.metadata?.image_edit_review as { status?: string })
              ?.status,
          ),
        )
      )
        return false;
      seen.add(artifact.id);
      return true;
    });
}

export default function ControllerResults({
  result,
  children,
  inputs,
  busy,
  onUse,
  active,
}: {
  result: ActionResult;
  children: (deliveredIds: ReadonlySet<string>) => ReactNode;
  inputs?: AssistantOptions;
  busy?: boolean;
  onUse?: (artifact: Artifact) => void;
  active: boolean;
}) {
  const steps = result.controller_steps ?? [];
  const finished = result.task_status
    ? TERMINAL.has(result.task_status)
    : steps.every((step) => TERMINAL.has(step.status));
  const [choice, setChoice] = useState<{
    finished: boolean;
    expanded: boolean;
  } | null>(null);
  const expanded = choice?.finished === finished ? choice.expanded : !finished;
  const id = useId();
  const artifacts = deliverables(result);

  return (
    <>
      {artifacts.length > 0 && (
        <section
          className="controller-deliverables"
          aria-label="Generated results"
        >
          {artifacts.map(({ artifact, studio }, index) => (
            <figure key={artifact.id}>
              {artifact.type === "image" && (
                <a
                  href={`/api/artifacts/${artifact.id}/file`}
                  target="_blank"
                  rel="noreferrer"
                  aria-label={`Open ${artifact.title || `image ${index + 1}`} in full size`}
                  tabIndex={active ? 0 : -1}
                >
                  <img
                    src={`/api/artifacts/${artifact.id}/file`}
                    alt={artifact.title || `Generated image ${index + 1}`}
                    loading="lazy"
                  />
                </a>
              )}
              {artifact.type === "video" && (
                <video
                  controls
                  preload="metadata"
                  src={`/api/artifacts/${artifact.id}/file`}
                  aria-label={
                    studio ? "Generated Studio film" : "Generated avatar video"
                  }
                  tabIndex={active ? 0 : -1}
                />
              )}
              {artifact.type === "audio" && (
                <audio
                  controls
                  preload="metadata"
                  src={`/api/artifacts/${artifact.id}/file`}
                  aria-label={
                    artifact.metadata?.capability === "audio.music"
                      ? "Generated music"
                      : "Generated speech"
                  }
                  tabIndex={active ? 0 : -1}
                />
              )}
              <figcaption>
                <Link to={`/library/${artifact.id}`} tabIndex={active ? 0 : -1}>
                  {artifact.title ||
                    `${artifact.type.charAt(0).toUpperCase()}${artifact.type.slice(1)} ${index + 1}`}
                </Link>
                {studio && (
                  <Link
                    to={`/studio/materials/${studio.id}${studio.revision ? `?revision=${encodeURIComponent(studio.revision)}` : ""}`}
                    tabIndex={active ? 0 : -1}
                  >
                    Open in Studio
                  </Link>
                )}
                {artifact.type === "audio" &&
                  artifact.metadata?.capability === "audio.music" &&
                  typeof artifact.metadata.lyrics === "string" &&
                  artifact.metadata.lyrics.trim() && (
                    <details>
                      <summary>Song lyrics</summary>
                      <p className="controller-result-lyrics">
                        {artifact.metadata.lyrics}
                      </p>
                    </details>
                  )}
                {onUse &&
                  (artifact.type === "image" ||
                    (artifact.type === "audio" &&
                      artifact.mime_type === "audio/wav" &&
                      artifact.metadata?.capability !== "audio.music")) && (
                    <Button
                      type="button"
                      variant="secondary"
                      disabled={
                        !active ||
                        busy ||
                        inputs?.image_artifact_ids.includes(artifact.id) ||
                        inputs?.audio_artifact_id === artifact.id ||
                        (artifact.type === "image" &&
                          (inputs?.image_artifact_ids.length ?? 0) >=
                            (inputs?.action === "image.describe" ? 4 : 8))
                      }
                      onClick={() => onUse(artifact)}
                    >
                      {inputs?.image_artifact_ids.includes(artifact.id) ||
                      inputs?.audio_artifact_id === artifact.id
                        ? "Added to next message"
                        : artifact.type === "image"
                          ? "Use as image reference"
                          : "Use as voice reference"}
                    </Button>
                  )}
              </figcaption>
            </figure>
          ))}
        </section>
      )}
      <section className="controller-activity" aria-label="Task activity">
        <button
          type="button"
          className="controller-activity-heading"
          aria-expanded={expanded}
          aria-controls={id}
          tabIndex={active ? 0 : -1}
          onClick={() => setChoice({ finished, expanded: !expanded })}
        >
          <ChevronDown aria-hidden="true" size={16} />
          <span>Task activity</span>
          <span className="controller-activity-count">
            {steps.length} {steps.length === 1 ? "step" : "steps"}
          </span>
        </button>
        {expanded && (
          <div id={id}>
            {children(new Set(artifacts.map(({ artifact }) => artifact.id)))}
          </div>
        )}
      </section>
    </>
  );
}
