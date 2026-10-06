import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ImagePlus, Mic, X, ArrowLeft, ArrowRight } from "lucide-react";
import LibraryPicker from "../components/media/LibraryPicker";
import { Button } from "../components/ui/button";
import { api, type Artifact } from "../api";
import { Badge, ErrorNotice } from "../components/common";

export type CodingScope = {
  project_id: string;
  expected_updated_at: string;
  files: string[];
  external_ai: boolean;
  explore?: boolean;
};
export type AssistantOptions = {
  action: string;
  image_artifact_ids: string[];
  audio_artifact_id?: string | null;
  coding: CodingScope | null;
};
type Project = { id: string; name: string; updated_at: string };
export type ActionResult = {
  steps?: {
    id: string;
    capability: string;
    status: string;
    summary: string;
    error_message: string;
    location: string;
  }[];
  artifacts?: Artifact[];
  task_status?: string;
};

export function AssistantResults({
  result,
  inputs,
  busy,
  onUse,
}: {
  result: ActionResult;
  inputs?: AssistantOptions;
  busy?: boolean;
  onUse?: (artifact: Artifact) => void;
}) {
  if (!result.steps) return null;
  return (
    <div className="assistant-results">
      <div className="row">
        <strong>Task</strong>
        {result.task_status && <Badge status={result.task_status} />}
      </div>
      {result.steps.map((step) => (
        <div className="content-panel" key={step.id}>
          <Link to={`/runs/${step.id}`}>{step.capability}</Link>{" "}
          <Badge status={step.status} />{" "}
          <span className="chip">{step.location.toUpperCase()}</span>
          {step.error_message && <p className="notice">{step.error_message}</p>}
        </div>
      ))}
      <div className="assistant-images">
        {result.artifacts?.map((artifact) => (
          <div key={artifact.id}>
            {artifact.type === "image" && (
              <a
                href={`/api/artifacts/${artifact.id}/file`}
                target="_blank"
                rel="noreferrer"
              >
                <img
                  src={`/api/artifacts/${artifact.id}/file`}
                  alt={artifact.original_filename || "Generated image"}
                />
              </a>
            )}
            {artifact.type === "video" && (
              <video
                controls
                preload="metadata"
                src={`/api/artifacts/${artifact.id}/file`}
                aria-label="Generated avatar video"
                style={{ maxWidth: "100%" }}
              />
            )}
            {artifact.type === "audio" && (
              <audio
                controls
                preload="metadata"
                src={`/api/artifacts/${artifact.id}/file`}
                aria-label="Generated speech"
              />
            )}
            <Link to={`/library/${artifact.id}`}>
              {artifact.title || artifact.original_filename || artifact.type}
            </Link>
            {onUse &&
              (artifact.type === "image" ||
                (artifact.type === "audio" &&
                  artifact.mime_type === "audio/wav")) && (
                <Button
                  type="button"
                  variant="secondary"
                  className="assistant-reuse-result"
                  disabled={
                    busy ||
                    inputs?.image_artifact_ids.includes(artifact.id) ||
                    inputs?.audio_artifact_id === artifact.id ||
                    (artifact.type === "image" &&
                      (inputs?.image_artifact_ids.length ?? 0) >= 8)
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
          </div>
        ))}
      </div>
    </div>
  );
}

export default function AssistantActions({
  value,
  onChange,
  busy,
  onUploading,
}: {
  value: AssistantOptions;
  onChange: (value: AssistantOptions) => void;
  busy: boolean;
  onUploading: (uploading: boolean) => void;
}) {
  const [error, setError] = useState<Error | null>(null);
  const imageInput = useRef<HTMLInputElement>(null);
  const voiceInput = useRef<HTMLInputElement>(null);
  const [projectId, setProjectId] = useState("");
  const [files, setFiles] = useState("");
  const [explore, setExplore] = useState(true);
  const [external, setExternal] = useState(false);
  const projects = useQuery({
    queryKey: ["coding-projects"],
    queryFn: () => api<Project[]>("/projects?limit=500"),
    enabled: value.action.startsWith("coding."),
  });
  function scope(
    id: string,
    paths: string,
    allow: boolean,
    action = value.action,
    auto = explore,
  ) {
    const localExplore = action === "coding.local" && auto;
    const project = projects.data?.find((p) => p.id === id);
    const selected = paths
      .split("\n")
      .map((p) => p.trim())
      .filter(Boolean);
    onChange({
      ...value,
      action,
      coding:
        (action === "coding.local" || (action === "coding.cursor" && allow)) &&
        project &&
        (selected.length || localExplore)
          ? {
              project_id: project.id,
              expected_updated_at: project.updated_at,
              files: localExplore ? [] : selected,
              ...(localExplore ? { explore: true } : {}),
              external_ai: action === "coding.cursor",
            }
          : null,
    });
  }
  async function upload(files: File[]) {
    if (busy) return;
    setError(null);
    if (files.length + value.image_artifact_ids.length > 8) {
      setError(new Error("Attach up to eight images."));
      return;
    }
    onUploading(true);
    const ids = [...value.image_artifact_ids];
    try {
      for (const file of files) {
        if (file.size > 20 * 1024 * 1024)
          throw new Error("Each image must be at most 20 MiB.");
        const data = new FormData();
        data.append("file", file);
        const artifact = await api<Artifact>("/images/uploads", {
          method: "POST",
          body: data,
        });
        ids.push(artifact.id);
        onChange({ ...value, image_artifact_ids: [...ids] });
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error("Upload failed"));
    } finally {
      onUploading(false);
    }
  }
  return (
    <fieldset disabled={busy} className="assistant-actions image-form">
      <label>
        Action
        <select
          aria-label="Action"
          value={value.action}
          onChange={(e) => {
            scope(projectId, files, false, e.target.value);
            setExternal(false);
          }}
        >
          <option value="auto">Auto — let AI Station route this task</option>
          <option value="chat">Conversation</option>
          <option value="image.generate">Generate image</option>
          <option value="image.edit">Edit image</option>
          <option value="image.recompose">Recompose references</option>
          <option value="image.upscale">Upscale image</option>
          <option value="audio.speech">
            Speech · read this message in Polish
          </option>
          <option value="avatar.animate">Animate portrait with speech</option>
          <option value="agent.create">Create agent</option>
          <option value="coding.local">Coding with Local AI</option>
          <option value="coding.cursor">Coding with Cursor</option>
        </select>
      </label>
      {!value.action.startsWith("coding.") && (
        <div className="assistant-attachment-toolbar">
          <Button
            type="button"
            variant="secondary"
            onClick={() => imageInput.current?.click()}
            disabled={value.image_artifact_ids.length >= 8}
          >
            <ImagePlus size={15} /> Add images
          </Button>
          <LibraryPicker
            kind="image"
            existing={value.image_artifact_ids}
            limit={8 - value.image_artifact_ids.length}
            busy={busy}
            onSelect={(items) =>
              onChange({
                ...value,
                image_artifact_ids: [
                  ...value.image_artifact_ids,
                  ...items.map((a) => a.id),
                ],
              })
            }
          />
          <Button
            type="button"
            variant="ghost"
            onClick={() => voiceInput.current?.click()}
          >
            <Mic size={15} />{" "}
            {value.audio_artifact_id ? "Replace voice" : "Add voice"}
          </Button>
          <LibraryPicker
            kind="audio"
            existing={value.audio_artifact_id ? [value.audio_artifact_id] : []}
            limit={1}
            busy={busy}
            onSelect={(items) =>
              onChange({ ...value, audio_artifact_id: items[0].id })
            }
          />
        </div>
      )}
      <input
        ref={voiceInput}
        hidden
        aria-label="Voice reference · WAV"
        type="file"
        accept="audio/wav,.wav"
        onChange={async (event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (!file) return;
          onUploading(true);
          setError(null);
          try {
            const body = new FormData();
            body.append("file", file);
            const artifact = await api<Artifact>("/audio/uploads", {
              method: "POST",
              body,
            });
            onChange({ ...value, audio_artifact_id: artifact.id });
          } catch (error) {
            setError(error as Error);
          } finally {
            onUploading(false);
          }
        }}
      />
      {value.audio_artifact_id && (
        <div className="assistant-voice-reference">
          <span>
            <Mic size={16} /> Voice reference
          </span>
          <audio
            controls
            preload="metadata"
            src={`/api/artifacts/${value.audio_artifact_id}/file`}
            aria-label="Voice reference preview"
          />
          <button
            type="button"
            className="icon-button"
            aria-label="Remove voice reference"
            onClick={() => onChange({ ...value, audio_artifact_id: null })}
          >
            <X size={16} />
          </button>
        </div>
      )}
      {(!value.action.startsWith("coding.") ||
        value.image_artifact_ids.length > 0) && (
        <div
          className="assistant-reference-area"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            void upload(Array.from(e.dataTransfer.files));
          }}
        >
          <input
            ref={imageInput}
            hidden
            aria-label="Image references"
            type="file"
            multiple
            accept="image/png,image/jpeg,image/webp"
            onChange={(e) => {
              const files = Array.from(e.target.files ?? []);
              e.target.value = "";
              void upload(files);
            }}
          />
          <p className="muted">
            Drop images here. Order matters — for example, person first,
            clothing second. Use the arrows to reorder.
          </p>
          <div className="assistant-reference-strip">
            {value.image_artifact_ids.map((id, index) => (
              <div className="assistant-reference" key={`${id}-${index}`}>
                <span className="assistant-reference-number">{index + 1}</span>
                <img
                  src={`/api/artifacts/${id}/file`}
                  alt={`Reference ${index + 1}`}
                />
                <button
                  className="assistant-reference-remove"
                  aria-label={`Remove reference ${index + 1}`}
                  type="button"
                  onClick={() =>
                    onChange({
                      ...value,
                      image_artifact_ids: value.image_artifact_ids.filter(
                        (_, i) => i !== index,
                      ),
                    })
                  }
                >
                  <X size={14} />
                </button>
                <div className="assistant-reference-order">
                  <button
                    type="button"
                    aria-label={`Move reference ${index + 1} earlier`}
                    disabled={busy || index === 0}
                    onClick={() => {
                      const ids = [...value.image_artifact_ids];
                      [ids[index - 1], ids[index]] = [
                        ids[index],
                        ids[index - 1],
                      ];
                      onChange({ ...value, image_artifact_ids: ids });
                    }}
                  >
                    <ArrowLeft size={13} />
                  </button>
                  <span>Reference {index + 1}</span>
                  <button
                    type="button"
                    aria-label={`Move reference ${index + 1} later`}
                    disabled={
                      busy || index === value.image_artifact_ids.length - 1
                    }
                    onClick={() => {
                      const ids = [...value.image_artifact_ids];
                      [ids[index + 1], ids[index]] = [
                        ids[index],
                        ids[index + 1],
                      ];
                      onChange({ ...value, image_artifact_ids: ids });
                    }}
                  >
                    <ArrowRight size={13} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      {value.action.startsWith("coding.") && (
        <details open className="assistant-coding-scope">
          <summary>Coding scope</summary>
          <label>
            Project
            <select
              aria-label="Project"
              value={projectId}
              onChange={(e) => {
                setProjectId(e.target.value);
                setExternal(false);
                scope(e.target.value, files, false);
              }}
            >
              <option value="">Select a registered project</option>
              {projects.data?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          {value.action === "coding.local" && (
            <label className="project-checkbox">
              <input
                type="checkbox"
                checked={explore}
                onChange={(e) => {
                  setExplore(e.target.checked);
                  scope(
                    projectId,
                    files,
                    false,
                    value.action,
                    e.target.checked,
                  );
                }}
              />
              Let Local AI find the relevant files
            </label>
          )}
          {value.action === "coding.local" && explore ? (
            <p className="muted">
              Local source exploration in a new worktree. Review selected files
              and changes in the resulting Run.
            </p>
          ) : (
            <>
              <label>
                Selected files
                <textarea
                  rows={3}
                  value={files}
                  placeholder="One repository-relative path per line"
                  onChange={(e) => {
                    setFiles(e.target.value);
                    setExternal(false);
                    scope(projectId, e.target.value, false);
                  }}
                />
              </label>
            </>
          )}
          {value.action === "coding.local" ? (
            <p className="muted">
              Uses this conversation's local model. Changes stay in a new
              worktree; review the diff and validation results here before
              committing.
            </p>
          ) : (
            <label>
              <input
                type="checkbox"
                checked={external}
                onChange={(e) => {
                  setExternal(e.target.checked);
                  scope(projectId, files, e.target.checked);
                }}
              />
              Allow sending this instruction, project guidance and selected file
              contents to external Cursor.
            </label>
          )}
          <ErrorNotice error={projects.error} />
        </details>
      )}
      <ErrorNotice error={error} />
    </fieldset>
  );
}
