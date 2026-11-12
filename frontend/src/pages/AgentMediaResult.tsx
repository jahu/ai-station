import { Link } from "react-router-dom";
import { Image, Music2, AudioLines, Film, LoaderCircle } from "lucide-react";
import type { Run } from "../api";
import { ErrorNotice } from "../components/common";
import MediaResult from "../components/media/MediaResult";
import MediaJobResult from "../components/media/MediaJobResult";

import AgentDocumentSources from "./AgentDocumentSources";
import "./AgentImageScenes.css";

export default function AgentMediaResult({ runs }: { runs: Run[] }) {
  const task = runs[0]?.task_id;
  const prepared = runs.find(
    (run) => run.task_id === task && run.executor_type === "agent_media",
  );
  const snapshot = prepared?.parameters?.media_context_snapshot;
  const context =
    snapshot && typeof snapshot === "object" && "observations" in snapshot
      ? snapshot.observations
      : null;
  const documents = Array.isArray(context)
    ? context
        .filter((item) => item?.tool === "read_documents")
        .map((item) => ({ result: item.result }))
    : [];
  const scene = prepared?.parameters?.image_scene as
    Record<string, unknown> | undefined;
  const image = runs.find(
    (row) => row.task_id === task && row.executor_type === "photo_pipe",
  );
  const changes =
    scene && typeof scene.changes === "object" && scene.changes !== null
      ? Object.entries(scene.changes).filter(
          (row): row is [string, string] => typeof row[1] === "string",
        )
      : scene &&
          ["setting", "pose", "expression"].every(
            (key) => typeof scene[key] === "string",
          )
        ? ["setting", "pose", "expression"].map(
            (key) => [key, String(scene[key])] as [string, string],
          )
        : [];
  const preserve = Array.isArray(scene?.preserve)
    ? scene.preserve.filter(
        (value): value is string => typeof value === "string",
      )
    : [];
  const generation = image?.parameters;
  const settings = generation
    ? [
        [
          "Backend",
          typeof generation.backend === "string" ? generation.backend : null,
        ],
        [
          "Steps",
          typeof generation.steps === "number"
            ? String(generation.steps)
            : null,
        ],
        [
          "Guidance (CFG)",
          typeof generation.cfg === "number" ? String(generation.cfg) : null,
        ],
        [
          "Dimensions",
          typeof generation.width === "number" &&
          typeof generation.height === "number"
            ? `${generation.width} × ${generation.height}`
            : null,
        ],
      ].filter((row): row is [string, string] => row[1] !== null)
    : [];
  return (
    <div className="agent-media-result">
      <AgentDocumentSources captures={documents} />
      {changes.length > 0 && (
        <section
          className="agent-image-scene-summary"
          aria-label="Image scene plan"
        >
          <h3>This run's image plan</h3>
          {preserve.length > 0 && (
            <p>
              <strong>Keep consistent:</strong> {preserve.join(" · ")}
            </p>
          )}
          <dl>
            {changes.map(([key, value]) => (
              <div key={key}>
                <dt>{key.charAt(0).toUpperCase() + key.slice(1)}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
          {settings.length > 0 && (
            <details>
              <summary>Generation settings</summary>
              <dl>
                {settings.map(([label, value]) => (
                  <div key={label}>
                    <dt>{label}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
            </details>
          )}
          {typeof image?.parameters?.prompt === "string" && (
            <details>
              <summary>Image prompt</summary>
              <p>{image.parameters.prompt}</p>
            </details>
          )}
        </section>
      )}
      <AgentMediaOutput runs={runs} />
    </div>
  );
}

function AgentMediaOutput({ runs }: { runs: Run[] }) {
  const task = runs[0]?.task_id;
  const current = runs.filter((run) => run.task_id === task);
  const effects = current.find(
    (run) => run.executor_type === "mmaudio_effects",
  );
  const preview = current.find(
    (run) => run.executor_type === "effects_preview",
  );
  if (effects)
    return (
      <>
        <MediaResult
          kind="audio"
          audioMode="effects"
          runId={effects.id}
          run={effects}
          allowRetry={false}
          error={
            effects.error_message ? new Error(effects.error_message) : null
          }
        />
        {preview && (
          <MediaResult
            kind="video"
            runId={preview.id}
            run={preview}
            allowRetry={false}
            error={
              preview.error_message ? new Error(preview.error_message) : null
            }
          />
        )}
      </>
    );
  const film = current.find(
    (run) =>
      run.executor_type === "media_compose" ||
      run.executor_type === "avatar_media_plan",
  );
  const output =
    current.find((run) => run.executor_type === "image_edit") ??
    current.find(
      (run) =>
        run.executor_type === "photo_pipe" ||
        run.executor_type === "ace_step_music" ||
        run.executor_type === "fish_speech" ||
        run.executor_type === "chatterbox",
    );
  const preparation = current.find(
    (run) => run.executor_type === "agent_media",
  );
  if (film)
    return (
      <MediaJobResult
        id={film.task_id}
        allowResume={false}
        spokenText={
          current.find((run) => run.executor_type === "chatterbox")?.parameters
            ?.text as string | undefined
        }
      />
    );
  if (output)
    return (
      <MediaResult
        kind={
          output.executor_type === "photo_pipe" ||
          output.executor_type === "image_edit"
            ? "image"
            : "audio"
        }
        audioMode={
          output.executor_type === "ace_step_music" ? "music" : "speech"
        }
        runId={output.id}
        run={output}
        allowRetry={false}
        error={output.error_message ? new Error(output.error_message) : null}
        steps={
          output.executor_type === "photo_pipe" ||
          output.executor_type === "image_edit"
            ? current
                .filter((run) => run.executor_type === "photo_pipe")
                .reverse()
            : undefined
        }
      />
    );
  const latest = preparation ?? current[0];
  if (!latest) return null;
  const stopped = ["canceled", "failed", "interrupted"].includes(latest.status);
  const scope = (
    latest.parameters?.definition as { media?: { kind: string } } | undefined
  )?.media;
  const Icon =
    scope?.kind === "video" || scope?.kind === "avatar"
      ? Film
      : scope?.kind === "music"
        ? Music2
        : scope?.kind === "speech"
          ? AudioLines
          : Image;
  return (
    <section
      className="panel agent-media-pending"
      aria-label="Agent media result"
    >
      <div className="media-composer-heading">
        <Icon size={20} />
        <h2>
          {stopped
            ? "No new media was published"
            : "Preparing your agent’s output"}
        </h2>
      </div>
      <p role="status" className="muted">
        {stopped ? (
          "Your saved settings and execution history are preserved. Review the details before running again."
        ) : latest.status === "waiting_for_approval" ? (
          "Review and approve the generation step below to continue."
        ) : (
          <>
            <LoaderCircle size={16} className="animate-spin" />
            Creative direction and reviewed sources are prepared before
            generation.
          </>
        )}
      </p>
      <ErrorNotice
        error={latest.error_message ? new Error(latest.error_message) : null}
      />
      <Link className="text-link" to={`/runs/${latest.id}`}>
        Inspect preparation
      </Link>
    </section>
  );
}
