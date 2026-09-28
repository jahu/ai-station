import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type Artifact } from "../api";
import { Badge, ErrorNotice } from "../components/common";

export type CodingScope = {
  project_id: string;
  expected_updated_at: string;
  files: string[];
  external_ai: true;
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

export function AssistantResults({ result }: { result: ActionResult }) {
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
              {artifact.original_filename || artifact.type}
            </Link>
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
  const [projectId, setProjectId] = useState("");
  const [files, setFiles] = useState("");
  const [external, setExternal] = useState(false);
  const projects = useQuery({
    queryKey: ["coding-projects"],
    queryFn: () => api<Project[]>("/projects?limit=500"),
    enabled: value.action === "coding.cursor",
  });
  function scope(id: string, paths: string, allow: boolean) {
    const project = projects.data?.find((p) => p.id === id);
    const selected = paths
      .split("\n")
      .map((p) => p.trim())
      .filter(Boolean);
    onChange({
      ...value,
      coding:
        allow && project && selected.length
          ? {
              project_id: project.id,
              expected_updated_at: project.updated_at,
              files: selected,
              external_ai: true,
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
            onChange({ ...value, action: e.target.value, coding: null });
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
          <option value="coding.cursor">Coding with Cursor</option>
        </select>
      </label>
      <label>
        Voice reference · WAV
        <input
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
      </label>
      {value.audio_artifact_id && (
        <div>
          <audio
            controls
            preload="metadata"
            src={`/api/artifacts/${value.audio_artifact_id}/file`}
            aria-label="Voice reference preview"
          />
          <button
            type="button"
            onClick={() => onChange({ ...value, audio_artifact_id: null })}
          >
            Remove voice reference
          </button>
        </div>
      )}
      <div
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          void upload(Array.from(e.dataTransfer.files));
        }}
      >
        <label>
          Image references
          <input
            type="file"
            multiple
            accept="image/png,image/jpeg,image/webp"
            onChange={(e) => {
              const files = Array.from(e.target.files ?? []);
              e.target.value = "";
              void upload(files);
            }}
          />
        </label>
        <p className="muted">
          Drop images here. Reference order follows upload order — for example,
          person first, clothing second.
        </p>
        <div className="assistant-images">
          {value.image_artifact_ids.map((id, index) => (
            <div key={`${id}-${index}`}>
              <img
                src={`/api/artifacts/${id}/file`}
                alt={`Reference ${index + 1}`}
              />
              <button
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
                Remove reference {index + 1}
              </button>
            </div>
          ))}
        </div>
      </div>
      {value.action === "coding.cursor" && (
        <details open>
          <summary>Coding scope</summary>
          <label>
            Project
            <select
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
          <ErrorNotice error={projects.error} />
        </details>
      )}
      <ErrorNotice error={error} />
    </fieldset>
  );
}
