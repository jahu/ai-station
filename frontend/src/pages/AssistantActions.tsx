import { useId, useRef, useState, type KeyboardEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ImagePlus, Mic, X, ArrowLeft, ArrowRight } from "lucide-react";
import LibraryPicker from "../components/media/LibraryPicker";
import { Button } from "../components/ui/button";
import { api, type Artifact, type Hardware, type Run } from "../api";
import { Badge, ErrorNotice } from "../components/common";
import CodingReview from "./CodingReview";
import GithubPublication from "./GithubPublication";
import { useListKeyboard } from "./useListKeyboard";
import { GpuChoiceList } from "./GpuChoiceList";

export type CodingScope = {
  project_id: string;
  expected_updated_at: string;
  files: string[];
  external_ai: boolean;
  executor?: "cursor" | "codex";
  explore?: boolean;
  max_repair_attempts?: number;
};
export type CommitScope = {
  source_run_id: string;
  message: string;
  reviewed: true;
};
export type PublishScope = {
  source_run_id: string;
  approved: true;
  repository: string;
  commit: string;
  base: string;
  expected_updated_at: string;
  title: string;
  body: string;
};
export type LoadScope = {
  model_file_id: string;
  gpus: number[];
  context_size: number;
  cache_type?: "f16" | "q8_0";
};
export type StopScope = { instance_id: string };
export type AssistantOptions = {
  action: string;
  image_artifact_ids: string[];
  audio_artifact_id?: string | null;
  coding: CodingScope | null;
  commit: CommitScope | null;
  publish: PublishScope | null;
  load: LoadScope | null;
  stop: StopScope | null;
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
  coding_runs?: Run[];
  task_status?: string;
};

export function AssistantResults({
  result,
  inputs,
  busy,
  onUse,
  onQueued,
}: {
  result: ActionResult;
  inputs?: AssistantOptions;
  busy?: boolean;
  onUse?: (artifact: Artifact) => void;
  onQueued?: (result: Run) => void;
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
      {result.coding_runs?.map((run) => (
        <div key={`coding-${run.id}`}>
          <CodingReview run={run} onQueued={onQueued} />
          <GithubPublication run={run} onQueued={onQueued} />
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

function proposalReady(run: Run) {
  const review = run.metadata?.coding_review as
    | { files?: unknown[] }
    | undefined;
  return (
    ["cursor_proposal", "codex_proposal", "local_proposal"].includes(
      run.executor_type,
    ) &&
    run.status === "succeeded" &&
    !run.metadata?.repair_run_id &&
    !run.metadata?.continuation_run_id &&
    !run.metadata?.commit_run_id &&
    !!review?.files?.length
  );
}

function commitReady(run: Run) {
  return (
    run.executor_type === "reviewed_commit" &&
    run.status === "succeeded" &&
    !!run.metadata?.git_commit &&
    !run.metadata?.publication_run_id
  );
}

function ImageReferenceStrip({
  ids,
  busy,
  onChange,
}: {
  ids: string[];
  busy: boolean;
  onChange: (ids: string[]) => void;
}) {
  const labelId = useId();
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    ids,
    (id) => id,
  );
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown(event);
    if (event.key === "Enter") event.preventDefault();
  };
  if (!ids.length) return null;
  return (
    <>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose an image reference while the list is focused. Remove
        and reorder stay on the selected reference. Enter does not send. There
        is no inspectable reference Run.
      </p>
      <div
        ref={listRef}
        className="assistant-reference-strip"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {ids.map((id, i) => {
          const current = i === index;
          const shortId = id.slice(0, 8);
          return (
            <div
              className="assistant-reference"
              key={id}
              aria-label={`Image reference ${i + 1} ${shortId}`}
              {...itemProps(i, id)}
            >
              <span className="assistant-reference-number">{i + 1}</span>
              <img src={`/api/artifacts/${id}/file`} alt={`Reference ${i + 1}`} />
              <button
                className="assistant-reference-remove"
                aria-label={`Remove reference ${i + 1} ${shortId}`}
                type="button"
                tabIndex={current ? 0 : -1}
                onClick={() => onChange(ids.filter((_, other) => other !== i))}
              >
                <X size={14} />
              </button>
              <div className="assistant-reference-order">
                <button
                  type="button"
                  aria-label={`Move reference ${i + 1} ${shortId} earlier`}
                  tabIndex={current ? 0 : -1}
                  disabled={busy || i === 0}
                  onClick={() => {
                    const next = [...ids];
                    [next[i - 1], next[i]] = [next[i], next[i - 1]];
                    onChange(next);
                  }}
                >
                  <ArrowLeft size={13} />
                </button>
                <span>Reference {i + 1}</span>
                <button
                  type="button"
                  aria-label={`Move reference ${i + 1} ${shortId} later`}
                  tabIndex={current ? 0 : -1}
                  disabled={busy || i === ids.length - 1}
                  onClick={() => {
                    const next = [...ids];
                    [next[i + 1], next[i]] = [next[i], next[i + 1]];
                    onChange(next);
                  }}
                >
                  <ArrowRight size={13} />
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}

export default function AssistantActions({
  value,
  onChange,
  busy,
  onUploading,
  sources = [],
}: {
  value: AssistantOptions;
  onChange: (value: AssistantOptions) => void;
  busy: boolean;
  onUploading: (uploading: boolean) => void;
  sources?: Run[];
}) {
  const [error, setError] = useState<Error | null>(null);
  const imageInput = useRef<HTMLInputElement>(null);
  const voiceInput = useRef<HTMLInputElement>(null);
  const [projectId, setProjectId] = useState("");
  const [files, setFiles] = useState("");
  const [explore, setExplore] = useState(true);
  const [repairAttempts, setRepairAttempts] = useState(0);
  const [external, setExternal] = useState(false);
  const [commitMessage, setCommitMessage] = useState("Apply reviewed changes");
  const [reviewed, setReviewed] = useState(false);
  const [publishTitle, setPublishTitle] = useState("Review AI Station changes");
  const [publishBody, setPublishBody] = useState("");
  const [publishApproved, setPublishApproved] = useState(false);
  const [publishSourceId, setPublishSourceId] = useState("");
  const [commitSourceId, setCommitSourceId] = useState("");
  const codingTask = ["coding.local", "coding.cursor", "coding.codex"].includes(
    value.action,
  );
  const proposals = sources.filter(proposalReady);
  const commits = sources.filter(commitReady);
  const projects = useQuery({
    queryKey: ["coding-projects"],
    queryFn: () => api<Project[]>("/projects?limit=500"),
    enabled: codingTask,
  });
  const publishSource = commits.find((run) => run.id === publishSourceId);
  const preview = useQuery({
    queryKey: ["publication-preview", publishSource?.id],
    queryFn: () =>
      api<{
        repository: string;
        commit: string;
        base: string;
        expected_updated_at: string;
        blocked_reason: string | null;
        github_cli_available: boolean;
      }>(`/coding/runs/${publishSource!.id}/publication`),
    enabled: value.action === "coding.publish" && !!publishSource,
    retry: false,
  });
  const hardware = useQuery({
    queryKey: ["hardware"],
    queryFn: () => api<Hardware>("/system/hardware"),
    enabled: value.action === "runtime.load",
  });
  const [loadGpus, setLoadGpus] = useState<number[] | null>(null);
  const [loadContext, setLoadContext] = useState(4096);
  const catalog = useQuery({
    queryKey: ["llama-models"],
    queryFn: () =>
      api<{
        models: { id: string; name: string }[];
        instances: {
          id: string;
          name: string;
          status: string;
          ownership: string;
        }[];
      }>("/llama"),
    enabled: value.action.startsWith("runtime."),
  });
  const selectedLoadGpus =
    loadGpus ?? (hardware.data?.gpus ?? []).map((gpu) => Number(gpu.index));
  const ownedInstances =
    catalog.data?.instances.filter(
      (instance) =>
        instance.ownership === "managed" &&
        !["stopped", "failed"].includes(instance.status),
    ) ?? [];
  function setLoad(modelId: string, gpus: number[], context: number) {
    onChange({
      action: "runtime.load",
      image_artifact_ids: [],
      audio_artifact_id: null,
      coding: null,
      commit: null,
      publish: null,
      stop: null,
      load: modelId
        ? { model_file_id: modelId, gpus, context_size: context }
        : null,
    });
  }
  function setStop(instanceId: string) {
    onChange({
      action: "runtime.stop",
      image_artifact_ids: [],
      audio_artifact_id: null,
      coding: null,
      commit: null,
      publish: null,
      load: null,
      stop: instanceId ? { instance_id: instanceId } : null,
    });
  }
  function resetAction(action: string) {
    setExternal(false);
    setReviewed(false);
    setPublishApproved(false);
    setCommitSourceId("");
    setPublishSourceId("");
    if (
      ["coding.commit", "coding.publish", "runtime.load", "runtime.stop"].includes(
        action,
      )
    ) {
      onChange({
        action,
        image_artifact_ids: [],
        audio_artifact_id: null,
        coding: null,
        commit: null,
        publish: null,
        load: null,
        stop: null,
      });
      return;
    }
    scope(projectId, files, false, action);
  }
  function setCommit(sourceId: string, message: string, confirmed: boolean) {
    onChange({
      action: "coding.commit",
      image_artifact_ids: [],
      audio_artifact_id: null,
      coding: null,
      publish: null,
      load: null,
      stop: null,
      commit:
        sourceId && message.trim() && confirmed
          ? { source_run_id: sourceId, message: message.trim(), reviewed: true }
          : null,
    });
  }
  function setPublish(
    sourceId: string,
    title: string,
    body: string,
    confirmed: boolean,
  ) {
    const target = preview.data;
    onChange({
      action: "coding.publish",
      image_artifact_ids: [],
      audio_artifact_id: null,
      coding: null,
      commit: null,
      load: null,
      stop: null,
      publish:
        sourceId &&
        title.trim() &&
        confirmed &&
        target &&
        !target.blocked_reason &&
        target.github_cli_available
          ? {
              source_run_id: sourceId,
              approved: true,
              repository: target.repository,
              commit: target.commit,
              base: target.base,
              expected_updated_at: target.expected_updated_at,
              title: title.trim(),
              body,
            }
          : null,
    });
  }
  function scope(
    id: string,
    paths: string,
    allow: boolean,
    action = value.action,
    auto = explore,
    repairs = repairAttempts,
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
      commit: null,
      publish: null,
      load: null,
      stop: null,
      coding:
        (action === "coding.local" ||
          (["coding.cursor", "coding.codex"].includes(action) && allow)) &&
        project &&
        (selected.length || localExplore)
          ? {
              project_id: project.id,
              expected_updated_at: project.updated_at,
              files: localExplore ? [] : selected,
              ...(localExplore ? { explore: true } : {}),
              ...(action === "coding.local" && repairs > 0
                ? { max_repair_attempts: repairs }
                : {}),
              external_ai: action !== "coding.local",
              ...(action === "coding.codex"
                ? { executor: "codex" as const }
                : {}),
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
          onChange={(e) => resetAction(e.target.value)}
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
          <option value="coding.codex">Coding with Codex</option>
          <option value="coding.commit">Commit reviewed changes</option>
          <option value="coding.publish">
            Publish reviewed commit to GitHub
          </option>
          <option value="runtime.load">Load local GGUF</option>
          <option value="runtime.stop">Unload owned llama.cpp</option>
        </select>
      </label>
      {!value.action.startsWith("coding.") &&
        !value.action.startsWith("runtime.") && (
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
      {((!value.action.startsWith("coding.") &&
        !value.action.startsWith("runtime.")) ||
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
          <ImageReferenceStrip
            ids={value.image_artifact_ids}
            busy={busy}
            onChange={(image_artifact_ids) =>
              onChange({ ...value, image_artifact_ids })
            }
          />
        </div>
      )}
      {value.action === "coding.commit" && (
        <details open className="assistant-coding-scope">
          <summary>Reviewed commit</summary>
          <p className="muted">
            Only proposals from this conversation can be committed. The model
            cannot grant Git write permission.
          </p>
          <label>
            Proposal
            <select
              aria-label="Commit proposal"
              value={commitSourceId}
              onChange={(event) => {
                setCommitSourceId(event.target.value);
                setCommit(event.target.value, commitMessage, reviewed);
              }}
            >
              <option value="">Select a reviewed coding proposal</option>
              {proposals.map((run) => (
                <option key={run.id} value={run.id}>
                  {run.summary || run.capability} · {run.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
          {!proposals.length && (
            <p className="notice">
              Finish a coding task in this conversation and review its diff
              first.
            </p>
          )}
          <label>
            Commit message
            <input
              maxLength={2000}
              value={commitMessage}
              onChange={(event) => {
                setCommitMessage(event.target.value);
                setCommit(commitSourceId, event.target.value, reviewed);
              }}
            />
          </label>
          <label className="project-checkbox">
            <input
              type="checkbox"
              checked={reviewed}
              onChange={(event) => {
                setReviewed(event.target.checked);
                setCommit(commitSourceId, commitMessage, event.target.checked);
              }}
            />
            I reviewed the diff and validation results.
          </label>
        </details>
      )}
      {value.action === "coding.publish" && (
        <details open className="assistant-coding-scope">
          <summary>GitHub publication</summary>
          <p className="muted">
            Approve the exact repository, commit and draft PR. This never
            merges. Enable task-branch push and integration PRs in the project
            first.
          </p>
          <label>
            Reviewed commit
            <select
              aria-label="Publish commit"
              value={publishSourceId}
              onChange={(event) => {
                setPublishSourceId(event.target.value);
                setPublishApproved(false);
                setPublish(event.target.value, publishTitle, publishBody, false);
              }}
            >
              <option value="">Select a successful reviewed commit</option>
              {commits.map((run) => (
                <option key={run.id} value={run.id}>
                  {String(
                    (run.metadata?.git_commit as { commit?: string })?.commit ??
                      run.id,
                  ).slice(0, 12)}
                </option>
              ))}
            </select>
          </label>
          {!commits.length && (
            <p className="notice">
              Commit reviewed changes in this conversation before publishing.
            </p>
          )}
          <ErrorNotice error={preview.error} />
          {preview.data?.blocked_reason && (
            <p className="notice">{preview.data.blocked_reason}</p>
          )}
          {preview.data &&
            !preview.data.blocked_reason &&
            !preview.data.github_cli_available && (
              <p className="notice">
                GitHub CLI is unavailable on the Host Runner.
              </p>
            )}
          {preview.data && (
            <p className="mono">
              {preview.data.repository}
              <br />
              {preview.data.base}
              <br />
              {preview.data.commit}
            </p>
          )}
          <label>
            PR title
            <input
              maxLength={200}
              value={publishTitle}
              onChange={(event) => {
                setPublishTitle(event.target.value);
                setPublish(
                  publishSourceId,
                  event.target.value,
                  publishBody,
                  publishApproved,
                );
              }}
            />
          </label>
          <label>
            PR description
            <textarea
              rows={4}
              maxLength={20000}
              value={publishBody}
              onChange={(event) => {
                setPublishBody(event.target.value);
                setPublish(
                  publishSourceId,
                  publishTitle,
                  event.target.value,
                  publishApproved,
                );
              }}
            />
          </label>
          <label className="project-checkbox">
            <input
              type="checkbox"
              checked={publishApproved}
              disabled={!preview.data || !!preview.data.blocked_reason}
              onChange={(event) => {
                setPublishApproved(event.target.checked);
                setPublish(
                  publishSourceId,
                  publishTitle,
                  publishBody,
                  event.target.checked,
                );
              }}
            />
            I approve publishing this commit and PR text to the GitHub repository
            shown above.
          </label>
        </details>
      )}
      {value.action === "runtime.load" && (
        <details open className="assistant-coding-scope">
          <summary>Owned llama.cpp load</summary>
          <p className="muted">
            Loads a discovered GGUF into an AI Station-owned runtime. External
            Ollama or ComfyUI processes are not stopped. The model cannot choose
            a file or GPUs.
          </p>
          <ErrorNotice error={catalog.error ?? hardware.error} />
          <label>
            GGUF model
            <select
              aria-label="GGUF model"
              value={value.load?.model_file_id ?? ""}
              onChange={(event) =>
                setLoad(event.target.value, selectedLoadGpus, loadContext)
              }
            >
              <option value="">Select a discovered language-model GGUF</option>
              {catalog.data?.models.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.name}
                </option>
              ))}
            </select>
          </label>
          {!catalog.isPending && !catalog.data?.models.length && (
            <p className="notice">
              No language-model GGUFs are discovered yet. Scan model folders in
              Models first.
            </p>
          )}
          <fieldset>
            <legend>GPUs</legend>
            <GpuChoiceList
              gpus={hardware.data?.gpus ?? []}
              selected={selectedLoadGpus}
              onChange={(next) => {
                setLoadGpus(next);
                setLoad(value.load?.model_file_id ?? "", next, loadContext);
              }}
            />
            <small>No cards selected uses CPU. Several cards split layers.</small>
          </fieldset>
          <label>
            Context size
            <input
              type="number"
              min={512}
              max={262144}
              step={256}
              aria-label="Context size"
              value={value.load?.context_size ?? loadContext}
              onChange={(event) => {
                const context = Number(event.target.value);
                setLoadContext(context);
                setLoad(
                  value.load?.model_file_id ?? "",
                  selectedLoadGpus,
                  context,
                );
              }}
            />
          </label>
        </details>
      )}
      {value.action === "runtime.stop" && (
        <details open className="assistant-coding-scope">
          <summary>Owned llama.cpp unload</summary>
          <p className="muted">
            Stops only the selected AI Station-owned instance after its consumers
            finish. External runtimes are not touched.
          </p>
          <ErrorNotice error={catalog.error} />
          <label>
            Runtime
            <select
              aria-label="Owned runtime"
              value={value.stop?.instance_id ?? ""}
              onChange={(event) => setStop(event.target.value)}
            >
              <option value="">Select an owned llama.cpp instance</option>
              {ownedInstances.map((instance) => (
                <option key={instance.id} value={instance.id}>
                  {instance.name} · {instance.status}
                </option>
              ))}
            </select>
          </label>
          {!ownedInstances.length && (
            <p className="notice">
              No owned llama.cpp instance is loaded. External servers cannot be
              unloaded here.
            </p>
          )}
        </details>
      )}
      {codingTask && (
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
          {value.action === "coding.local" && explore && (
            <small>
              Public URLs in the task are fetched automatically. Local AI may
              GET further public pages and, when the Host Runner has search
              configured, query the public web. Private and loopback addresses
              are blocked. JavaScript is not executed; this is not a browser.
            </small>
          )}
          {value.action === "coding.local" && (
            <label>
              Automatic repair
              <select
                value={repairAttempts}
                onChange={(event) => {
                  const attempts = Number(event.target.value);
                  setRepairAttempts(attempts);
                  scope(
                    projectId,
                    files,
                    false,
                    value.action,
                    explore,
                    attempts,
                  );
                }}
              >
                <option value={0}>Off — I will request repairs</option>
                <option value={1}>Try once if validation fails</option>
                <option value={2}>Try up to twice if validation fails</option>
              </select>
              <small>
                Same local model, files and saved checks. Commit still requires
                your review.
              </small>
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
              contents to external{" "}
              {value.action === "coding.codex" ? "Codex" : "Cursor"}.
            </label>
          )}
          <ErrorNotice error={projects.error} />
        </details>
      )}
      <ErrorNotice error={error} />
    </fieldset>
  );
}
