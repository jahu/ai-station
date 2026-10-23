import ConversationDataControls from "./ConversationDataControls";
import AgentDataResult from "./AgentDataResult";
import type { ConversationDataScope } from "./useDataInputs";
import RecordingButton from "../components/media/RecordingButton";
import MusicScope from "./MusicScope";
import type { ConversationMusicOptions as MusicScopeOptions } from "./music-scope";
import { TRANSCRIPTION_AUDIO_ACCEPT } from "../recording-formats";
import { TranscriptResult } from "./Transcription";
import GithubSnapshotResult, {
  type GithubSnapshot,
} from "./GithubSnapshotResult";
import MediaJobResult from "../components/media/MediaJobResult";
import type { MediaJob } from "../components/media/media-job";
import { useId, useRef, useState, type KeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ImagePlus, Mic, X, ArrowLeft, ArrowRight } from "lucide-react";
import LibraryPicker from "../components/media/LibraryPicker";
import { Button } from "../components/ui/button";
import { api, type Artifact, type Hardware, type Run } from "../api";
import { Badge, ErrorNotice } from "../components/common";
import CodingReview from "./CodingReview";
import GithubPublication from "./GithubPublication";
import { useListKeyboard } from "./useListKeyboard";
import { FileChoiceList } from "./FileChoiceList";
import { ConsentChoiceList } from "./ConsentChoiceList";
import { PublicationChoiceList } from "./PublicationChoiceList";
import { ReviewChoiceList } from "./ReviewChoiceList";
import { ExploreChoiceList } from "./ExploreChoiceList";
import { RepairChoiceList } from "./RepairChoiceList";
import { parseFilePaths } from "./filePaths";
import { GpuChoiceList } from "./GpuChoiceList";
import { ActionChoiceList } from "./ActionChoiceList";
import { ArtifactLineage } from "./ArtifactLineage";
import LibraryActions from "./LibraryActions";
import { ProjectChoiceList } from "./ProjectChoiceList";
import { CodingModelChoiceList } from "./CodingModelChoiceList";
import { NewProjectBuild } from "./NewProjectBuild";
import { newProjectScope, type NewProjectScope } from "./new-project-scope";
import { GgufChoiceList } from "./GgufChoiceList";
import { RuntimeChoiceList } from "./RuntimeChoiceList";
import {
  CommitChoiceList,
  ProposalChoiceList,
} from "./AssistantGitChoiceLists";

export type CodingScope = {
  project_id: string;
  expected_updated_at: string;
  files: string[];
  external_ai: boolean;
  executor?: "cursor" | "codex";
  explore?: boolean;
  max_repair_attempts?: number;
  model?: string;
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
export type GithubScope = { connector_id: string; expected_updated_at: string };
export type AssistantOptions = {
  data?: ConversationDataScope | null;
  music?: MusicScopeOptions | null;
  github?: GithubScope | null;
  action: string;
  image_artifact_ids: string[];
  audio_artifact_id?: string | null;
  coding: CodingScope | null;
  new_project?: NewProjectScope | null;
  commit: CommitScope | null;
  publish: PublishScope | null;
  load: LoadScope | null;
  stop: StopScope | null;
  upscale_result?: boolean;
  speech_text?: string | null;
  media?: {
    duration_seconds: number;
    composition_mode: "continuous" | "shots";
  } | null;
};
type Project = { id: string; name: string; updated_at: string };
type TaskStep = {
  id: string;
  capability: string;
  status: string;
  summary: string;
  error_message: string;
  location: string;
};
export type ActionResult = {
  data_runs?: Run[];
  data_model?: string | null;
  github_snapshots?: GithubSnapshot[];
  transcriptions?: Run[];
  media_job?: MediaJob;
  steps?: TaskStep[];
  artifacts?: Artifact[];
  coding_runs?: Run[];
  task_status?: string;
  created_projects?: {
    id: string;
    name: string;
    updated_at: string;
    coding_task_id?: string;
  }[];
};
const IMAGE_STEPS = new Set([
  "image.generate",
  "image.edit",
  "image.recompose",
  "image.upscale",
]);
const RETRYABLE = new Set(["failed", "canceled", "interrupted"]);

function imageRetryable(step: TaskStep, steps: TaskStep[]) {
  if (!IMAGE_STEPS.has(step.capability) || !RETRYABLE.has(step.status))
    return false;
  const index = steps.findIndex((row) => row.id === step.id);
  return !steps.slice(index + 1).some((row) => IMAGE_STEPS.has(row.capability));
}

function ImageStepRetry({
  step,
  busy,
  onQueued,
}: {
  step: TaskStep;
  busy?: boolean;
  onQueued?: (result: Run) => void;
}) {
  const cache = useQueryClient();
  const retry = useMutation({
    mutationFn: () =>
      api<Run>(`/images/runs/${step.id}/retry`, { method: "POST" }),
    onSuccess: (next) => {
      cache.setQueryData(["run", next.id], next);
      void cache.invalidateQueries({ queryKey: ["conversation"] });
      void cache.invalidateQueries({ queryKey: ["runs"] });
      onQueued?.(next);
    },
  });
  return (
    <div className="assistant-step-retry">
      <p className="muted">
        A retry creates a new run with the same parameters and source images.
        Inspect logs and any partial output before repeating an interrupted run.
        The conversation stays here.
      </p>
      <ErrorNotice error={retry.error} />
      <Button
        type="button"
        variant="secondary"
        disabled={busy || retry.isPending}
        aria-label={`Retry as a new run ${step.id.slice(0, 8)}`}
        onClick={() => retry.mutate()}
      >
        {retry.isPending ? "Retrying…" : "Retry as a new run"}
      </Button>
    </div>
  );
}

function TaskSteps({
  steps,
  busy,
  onQueued,
}: {
  steps: TaskStep[];
  busy?: boolean;
  onQueued?: (run: Run) => void;
}) {
  return (
    <>
      {steps.map((step) => (
        <div className="content-panel" key={step.id}>
          <Link to={`/runs/${step.id}`}>{step.capability}</Link>{" "}
          <Badge status={step.status} />{" "}
          <span className="chip">{step.location.toUpperCase()}</span>
          {step.error_message && <p className="notice">{step.error_message}</p>}
          {imageRetryable(step, steps) && (
            <ImageStepRetry step={step} busy={busy} onQueued={onQueued} />
          )}
        </div>
      ))}
    </>
  );
}

export function AssistantResults({
  result,
  inputs,
  busy,
  onUse,
  onQueued,
  onProject,
  onData,
}: {
  result: ActionResult;
  onData?: (scope: ConversationDataScope) => void;
  inputs?: AssistantOptions;
  busy?: boolean;
  onUse?: (artifact: Artifact) => void;
  onQueued?: (result: Run) => void;
  onProject?: (project: {
    id: string;
    name: string;
    updated_at: string;
  }) => void;
}) {
  if (result.media_job)
    return (
      <MediaJobResult id={result.media_job.task_id} job={result.media_job} />
    );
  if (!result.steps) return null;
  const dataRoot = result.data_runs?.find(
    (run) => run.executor_type === "orchestrator",
  );
  const dataScope = dataRoot?.parameters.data as
    ConversationDataScope | undefined;
  const hasDataResult = result.data_runs?.some(
    (run) => run.status === "succeeded" && run.metadata?.data_result,
  );
  return (
    <div className="assistant-results">
      <div className="row">
        <strong>Task</strong>
        {result.task_status && <Badge status={result.task_status} />}
      </div>
      {result.data_runs?.length ? (
        <>
          <AgentDataResult runs={result.data_runs} />
          {onData && hasDataResult && dataScope?.input_artifact_ids?.length ? (
            <Button
              type="button"
              variant="secondary"
              disabled={busy}
              onClick={() =>
                onData({
                  ...dataScope,
                  input_artifact_ids: [...dataScope.input_artifact_ids],
                })
              }
            >
              Ask another question about these files
            </Button>
          ) : null}
          <p className="muted">
            LOCAL · {result.data_model || "Automatic local model"} · Originals
            unchanged
          </p>
        </>
      ) : null}
      {result.data_runs?.length ? (
        <details>
          <summary>Execution details</summary>
          <TaskSteps steps={result.steps} busy={busy} onQueued={onQueued} />
        </details>
      ) : (
        <TaskSteps steps={result.steps} busy={busy} onQueued={onQueued} />
      )}
      {result.transcriptions?.map((run) => (
        <TranscriptResult key={run.id} run={run} />
      ))}
      {result.github_snapshots?.map((snapshot) => (
        <GithubSnapshotResult key={snapshot.run_id} value={snapshot} />
      ))}
      {result.created_projects?.map((project) => (
        <section
          className="content-panel"
          key={`project-${project.id}`}
          aria-label={`Created project ${project.name}`}
        >
          <strong>{project.name}</strong>
          <p className="muted">
            Your Git repository and Python environment are ready.
          </p>
          <div className="row">
            <Link className="text-link" to={`/projects/${project.id}`}>
              Open project
            </Link>
            <Link
              className="text-link"
              to={
                project.coding_task_id
                  ? `/coding/${project.coding_task_id}`
                  : `/coding?project=${project.id}`
              }
            >
              Open Coding workspace
            </Link>
            {onProject && (
              <Button
                type="button"
                variant="secondary"
                disabled={busy}
                onClick={() => onProject(project)}
              >
                Continue here with Local AI
              </Button>
            )}
          </div>
        </section>
      ))}
      {result.coding_runs?.map((run) => (
        <div key={`coding-${run.id}`}>
          {run.project_id ? (
            <>
              <Link
                className="text-link"
                to={`/projects/${run.project_id}`}
                aria-label={`Inspect project ${run.project_id}`}
              >
                Inspect project
              </Link>
              {" · "}
              <Link
                className="text-link"
                to={`/runs?project_id=${run.project_id}`}
                aria-label={`View tagged Runs ${run.project_id}`}
              >
                View tagged Runs
              </Link>
            </>
          ) : null}
          <CodingReview run={run} onQueued={onQueued} />
          <GithubPublication run={run} onQueued={onQueued} />
        </div>
      ))}
      <div className="assistant-images">
        {result.artifacts
          ?.filter(
            (artifact) =>
              !result.data_runs?.length &&
              artifact.metadata?.song_preparation !== true &&
              !result.transcriptions?.some(
                (run) => run.id === artifact.run_id,
              ) &&
              !result.github_snapshots?.some(
                (snapshot) => snapshot.artifact_id === artifact.id,
              ),
          )
          .map((artifact) => (
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
                  aria-label={
                    artifact.metadata?.capability === "audio.music"
                      ? "Generated music"
                      : "Generated speech"
                  }
                />
              )}
              {artifact.type === "audio" &&
                artifact.metadata?.capability === "audio.music" &&
                typeof artifact.metadata.lyrics === "string" &&
                artifact.metadata.lyrics.trim() && (
                  <section
                    className="media-spoken-text"
                    aria-label={`Song lyrics ${artifact.id}`}
                  >
                    <h3>Song lyrics</h3>
                    <p>{artifact.metadata.lyrics}</p>
                  </section>
                )}
              <Link to={`/library/${artifact.id}`}>
                {artifact.title || artifact.original_filename || artifact.type}
              </Link>
              <LibraryActions artifact={artifact} />
              {onUse &&
                (artifact.type === "image" ||
                  (artifact.type === "audio" &&
                    artifact.metadata?.capability !== "audio.music" &&
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
              {artifact.type === "image" && (
                <div className="media-result-reuse">
                  {(
                    [
                      ["img2img", "Edit"],
                      ["recompose", "Recompose"],
                      ["upscale", "Upscale"],
                    ] as const
                  ).map(([mode, label]) => (
                    <Button key={mode} asChild variant="secondary">
                      <Link
                        to={`/images?mode=${mode}&input=${artifact.id}${
                          artifact.run_id ? `&run=${artifact.run_id}` : ""
                        }`}
                        aria-label={`${label} ${artifact.id.slice(0, 8)}`}
                      >
                        {label}
                      </Link>
                    </Button>
                  ))}
                  <Button asChild variant="secondary">
                    <Link
                      to={`/avatars?image=${artifact.id}`}
                      aria-label={`Use as portrait ${artifact.id.slice(0, 8)}`}
                    >
                      Use as portrait
                    </Link>
                  </Button>
                </div>
              )}
              {artifact.type === "audio" &&
                artifact.metadata?.capability !== "audio.music" &&
                artifact.mime_type === "audio/wav" && (
                  <div className="media-result-reuse">
                    <Button asChild variant="secondary">
                      <Link
                        to={`/audio?input=${artifact.id}${
                          artifact.run_id ? `&run=${artifact.run_id}` : ""
                        }`}
                        aria-label={`Use in Audio ${artifact.id.slice(0, 8)}`}
                      >
                        Use in Audio
                      </Link>
                    </Button>
                    <Button asChild variant="secondary">
                      <Link
                        to={`/avatars?audio=${artifact.id}`}
                        aria-label={`Use as speech ${artifact.id.slice(0, 8)}`}
                      >
                        Use as speech
                      </Link>
                    </Button>
                  </div>
                )}
              <ArtifactLineage artifactId={artifact.id} />
            </div>
          ))}
      </div>
    </div>
  );
}

function proposalReady(run: Run) {
  const review = run.metadata?.coding_review as
    { files?: unknown[] } | undefined;
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
              <img
                src={`/api/artifacts/${id}/file`}
                alt={`Reference ${i + 1}`}
              />
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
  allowWork = true,
  description,
}: {
  value: AssistantOptions;
  onChange: (value: AssistantOptions) => void;
  busy: boolean;
  onUploading: (uploading: boolean) => void;
  sources?: Run[];
  allowWork?: boolean;
  description?: string;
}) {
  const repositories = useQuery({
    queryKey: ["connectors"],
    queryFn: () =>
      api<
        {
          id: string;
          name: string;
          kind: string;
          enabled: boolean;
          repository: string;
          updated_at: string;
        }[]
      >("/connectors"),
    enabled: value.action === "github.inspect",
  });
  const [error, setError] = useState<Error | null>(null);
  const recordingInput =
    ["audio.transcribe", "audio.analyze"].includes(value.action) ||
    (value.action === "auto" && !value.image_artifact_ids.length);
  const imageInput = useRef<HTMLInputElement>(null);
  const voiceInput = useRef<HTMLInputElement>(null);
  const [projectId, setProjectId] = useState(value.coding?.project_id ?? "");
  const [files, setFiles] = useState(value.coding?.files.join("\n") ?? "");
  const [explore, setExplore] = useState(value.coding?.explore ?? true);
  const [repairAttempts, setRepairAttempts] = useState(
    value.coding?.max_repair_attempts ?? 0,
  );
  const [codingModel, setCodingModel] = useState(value.coding?.model ?? "");
  const [localCodingAuto, setLocalCodingAuto] = useState(
    !value.coding || value.coding.model === "auto",
  );
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
  const externalCoding =
    value.action === "coding.cursor" || value.action === "coding.codex";
  const codingProvider = value.action === "coding.codex" ? "codex" : "cursor";
  const proposals = sources.filter(proposalReady);
  const commits = sources.filter(commitReady);
  const projects = useQuery({
    queryKey: ["coding-projects"],
    queryFn: () => api<Project[]>("/projects?limit=500"),
    enabled: codingTask,
  });
  const codingCatalog = useQuery({
    queryKey: ["coding-models", codingProvider],
    queryFn: () =>
      api<{ models: { id: string; name: string }[]; notice: string }>(
        `/coding/models/${codingProvider}`,
      ),
    enabled: externalCoding,
    staleTime: 120000,
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
  async function attachAudio(file: File, rejectOnError = false) {
    onUploading(true);
    setError(null);
    try {
      const body = new FormData();
      body.append("file", file);
      const artifact = await api<Artifact>(
        recordingInput ? "/audio/transcription/uploads" : "/audio/uploads",
        {
          method: "POST",
          body,
        },
      );
      onChange({
        ...value,
        audio_artifact_id: artifact.id,
        upscale_result: false,
      });
    } catch (error) {
      setError(error as Error);
      if (rejectOnError) throw error;
    } finally {
      onUploading(false);
    }
  }
  function resetAction(action: string) {
    if (action === "data.analyze") {
      onChange({
        action,
        data: {
          input_artifact_ids: [],
          max_repairs: 1,
          model: "auto",
          maximum_runtime: 600,
        },
        image_artifact_ids: [],
        audio_artifact_id: null,
        coding: null,
        new_project: null,
        commit: null,
        publish: null,
        load: null,
        stop: null,
      });
      return;
    }
    if (action === "audio.music") {
      onChange({
        action,
        music: {},
        image_artifact_ids: [],
        audio_artifact_id: null,
        coding: null,
        new_project: null,
        commit: null,
        publish: null,
        load: null,
        stop: null,
        media: null,
        github: null,
        speech_text: null,
        upscale_result: false,
      });
      return;
    }
    if (["audio.transcribe", "audio.analyze"].includes(action)) {
      onChange({
        ...value,
        data: null,
        action,
        image_artifact_ids: [],
        coding: null,
        new_project: null,
        commit: null,
        publish: null,
        load: null,
        stop: null,
        media: null,
        github: null,
        upscale_result: false,
        speech_text: null,
        music: null,
      });
      return;
    }
    if (action === "project.create_code") {
      onChange({
        action,
        image_artifact_ids: [],
        audio_artifact_id: null,
        coding: null,
        new_project: { ...newProjectScope },
        commit: null,
        publish: null,
        load: null,
        stop: null,
      });
      return;
    }
    setExternal(false);
    setCodingModel("");
    setReviewed(false);
    setPublishApproved(false);
    setCommitSourceId("");
    setPublishSourceId("");
    if (action === "image.describe") {
      onChange({
        ...value,
        data: null,
        new_project: null,
        github: undefined,
        music: null,
        action,
        upscale_result: false,
        speech_text: null,
        audio_artifact_id: null,
        coding: null,
        commit: null,
        publish: null,
        load: null,
        stop: null,
      });
      return;
    }
    if (
      [
        "coding.commit",
        "coding.publish",
        "runtime.load",
        "runtime.stop",
        "system.inspect",
        "github.inspect",
        "image.generate_video",
        "project.create",
      ].includes(action)
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
    nativeModel = codingModel,
    localAuto = localCodingAuto,
  ) {
    const autoExplore =
      ["coding.local", "coding.cursor", "coding.codex"].includes(action) &&
      auto;
    const project = projects.data?.find((p) => p.id === id);
    const selected = parseFilePaths(paths);
    onChange({
      ...value,
      data: null,
      new_project: null,
      github: undefined,
      action,
      media: action === "video.generate" ? value.media : null,
      music: null,
      commit: null,
      publish: null,
      load: null,
      stop: null,
      coding:
        (action === "coding.local" ||
          (["coding.cursor", "coding.codex"].includes(action) && allow)) &&
        project &&
        (selected.length || autoExplore)
          ? {
              project_id: project.id,
              expected_updated_at: project.updated_at,
              files: autoExplore ? [] : selected,
              ...(autoExplore ? { explore: true } : {}),
              ...(action === "coding.local" && repairs > 0
                ? { max_repair_attempts: repairs }
                : {}),
              external_ai: action !== "coding.local",
              ...(action === "coding.codex"
                ? { executor: "codex" as const }
                : {}),
              ...(action === "coding.local"
                ? { model: localAuto ? "auto" : "" }
                : nativeModel
                  ? { model: nativeModel }
                  : {}),
            }
          : null,
    });
  }
  async function upload(files: File[]) {
    if (busy) return;
    setError(null);
    const imageLimit = value.action === "image.describe" ? 4 : 8;
    if (files.length + value.image_artifact_ids.length > imageLimit) {
      setError(new Error(`Attach up to ${imageLimit} images.`));
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
    <>
      <fieldset disabled={busy} className="assistant-actions image-form">
        <div>
          <ActionChoiceList
            value={value.action}
            disabled={busy}
            allowWork={allowWork}
            onChange={resetAction}
          />
        </div>
        {value.action === "data.analyze" && (
          <ConversationDataControls
            value={value.data}
            disabled={busy}
            onUploading={onUploading}
            onChange={(data) => onChange({ ...value, data })}
          />
        )}
        {value.audio_artifact_id &&
          value.image_artifact_ids.length === 1 &&
          ["auto", "avatar.animate"].includes(value.action) && (
            <label>
              Words to say (optional)
              <textarea
                value={value.speech_text ?? ""}
                maxLength={1000}
                rows={3}
                onChange={(event) =>
                  onChange({
                    ...value,
                    speech_text: event.target.value.trim()
                      ? event.target.value
                      : null,
                  })
                }
                placeholder="Leave empty to animate the recording, or type Polish text using its voice."
              />
            </label>
          )}
        {!value.audio_artifact_id &&
          !value.coding &&
          ["auto", "image.generate", "image.edit", "image.recompose"].includes(
            value.action,
          ) && (
            <label className="image-workflow-option">
              <input
                type="checkbox"
                checked={value.upscale_result ?? false}
                onChange={(event) =>
                  onChange({ ...value, upscale_result: event.target.checked })
                }
              />
              <span>
                Upscale image result 4×
                <small>After generation or editing; keeps both images.</small>
              </span>
            </label>
          )}
        {!value.action.startsWith("coding.") &&
          !value.action.startsWith("runtime.") &&
          value.action !== "system.inspect" &&
          value.action !== "github.inspect" &&
          value.action !== "data.analyze" &&
          value.action !== "audio.music" &&
          value.action !== "image.generate_video" &&
          value.action !== "project.create" &&
          value.action !== "project.create_code" && (
            <div className="assistant-attachment-toolbar">
              {["auto", "chat"].includes(value.action) && (
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => resetAction("data.analyze")}
                >
                  CSV / Excel
                </Button>
              )}
              {!["audio.transcribe", "audio.analyze"].includes(
                value.action,
              ) && (
                <>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => imageInput.current?.click()}
                    disabled={
                      value.image_artifact_ids.length >=
                      (value.action === "image.describe" ? 4 : 8)
                    }
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
                </>
              )}
              <Button
                type="button"
                variant="ghost"
                onClick={() => voiceInput.current?.click()}
              >
                <Mic size={15} />{" "}
                {recordingInput
                  ? value.audio_artifact_id
                    ? "Replace recording"
                    : "Add recording"
                  : value.audio_artifact_id
                    ? "Replace voice"
                    : "Add voice"}
              </Button>
              <LibraryPicker
                kind="audio"
                audioMode={recordingInput ? "transcription" : "voice"}
                existing={
                  value.audio_artifact_id ? [value.audio_artifact_id] : []
                }
                limit={1}
                busy={busy}
                onSelect={(items) =>
                  onChange({
                    ...value,
                    audio_artifact_id: items[0].id,
                    upscale_result: false,
                  })
                }
              />
            </div>
          )}
        <input
          ref={voiceInput}
          hidden
          aria-label={
            recordingInput
              ? "Recording · WAV, MP3, M4A, Ogg, WebM or FLAC"
              : "Voice reference · WAV"
          }
          type="file"
          accept={
            recordingInput ? TRANSCRIPTION_AUDIO_ACCEPT : "audio/wav,.wav"
          }
          onChange={async (event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (!file) return;
            await attachAudio(file);
          }}
        />
        {value.audio_artifact_id && (
          <div className="assistant-voice-reference">
            <span>
              <Mic size={16} />{" "}
              {recordingInput ? "Recording" : "Voice reference"}
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
              onClick={() =>
                onChange({
                  ...value,
                  audio_artifact_id: null,
                  speech_text: null,
                })
              }
            >
              <X size={16} />
            </button>
          </div>
        )}
        {((!value.action.startsWith("coding.") &&
          !value.action.startsWith("runtime.") &&
          value.action !== "image.generate_video" &&
          value.action !== "project.create" &&
          value.action !== "project.create_code" &&
          value.action !== "data.analyze" &&
          value.action !== "audio.music" &&
          value.action !== "github.inspect") ||
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
                onChange({
                  ...value,
                  image_artifact_ids,
                  speech_text:
                    image_artifact_ids.length === 1 ? value.speech_text : null,
                })
              }
            />
          </div>
        )}
        {value.action === "github.inspect" && (
          <label>
            GitHub repository
            <select
              aria-label="GitHub repository"
              value={value.github?.connector_id ?? ""}
              onChange={(event) => {
                const selected = repositories.data?.find(
                  (row) => row.id === event.target.value,
                );
                onChange({
                  ...value,
                  github: selected
                    ? {
                        connector_id: selected.id,
                        expected_updated_at: selected.updated_at,
                      }
                    : null,
                });
              }}
            >
              <option value="">Choose a connected repository</option>
              {repositories.data
                ?.filter((row) => row.kind === "github" && row.enabled)
                .map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.name} · {row.repository}
                  </option>
                ))}
            </select>
            <span className="muted">
              Reads issue and PR titles through your host GitHub login. No
              source files or account data are sent to an AI provider.{" "}
              <Link to="/settings/integrations">Connect a repository</Link>
            </span>
            <ErrorNotice error={repositories.error} />
          </label>
        )}
        {value.action === "audio.music" && (
          <MusicScope
            value={value.music ?? {}}
            lyricsSource={value.music?.lyrics_source ?? "fixed"}
            descriptionLimit={
              value.music?.lyrics_source === "goal" ? 16000 : 512
            }
            onLyricsSourceChange={(lyrics_source) =>
              onChange({ ...value, music: { ...value.music, lyrics_source } })
            }
            descriptionLength={description?.trim().length}
            onChange={(music, rememberedSource) =>
              onChange({
                ...value,
                music: {
                  ...music,
                  lyrics_source:
                    music.instrumental !== false
                      ? "fixed"
                      : (rememberedSource ??
                        (value.music?.instrumental !== false
                          ? "goal"
                          : (value.music?.lyrics_source ?? "fixed"))),
                },
              })
            }
          />
        )}
        {value.action === "video.generate" && (
          <label>
            Video length
            <select
              value={value.media?.duration_seconds ?? "preview"}
              disabled={busy}
              onChange={(event) =>
                onChange({
                  ...value,
                  media:
                    event.target.value === "preview"
                      ? null
                      : {
                          duration_seconds: Number(event.target.value),
                          composition_mode: "continuous",
                        },
                })
              }
            >
              <option value="preview">
                Short preview · or describe the duration
              </option>
              <option value="15">15 seconds</option>
              <option value="30">30 seconds</option>
              <option value="60">60 seconds</option>
            </select>
          </label>
        )}
        {value.action === "project.create_code" && (
          <NewProjectBuild
            busy={busy}
            value={value.new_project ?? newProjectScope}
            onChange={(new_project) => onChange({ ...value, new_project })}
          />
        )}
        {value.action === "coding.commit" && (
          <details open className="assistant-coding-scope">
            <summary>Reviewed commit</summary>
            <p className="muted">
              Only proposals from this conversation can be committed. The model
              cannot grant Git write permission.
            </p>
            <div>
              <span>Proposal</span>
              <ProposalChoiceList
                proposals={proposals.map((run) => ({
                  id: run.id,
                  title: `${run.summary || run.capability} · ${run.id.slice(0, 8)}`,
                  detail: run.executor_type,
                }))}
                value={commitSourceId}
                disabled={busy}
                onChange={(id) => {
                  setCommitSourceId(id);
                  setCommit(id, commitMessage, reviewed);
                }}
              />
            </div>
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
            <ReviewChoiceList
              checked={reviewed}
              disabled={busy}
              onChange={(next) => {
                setReviewed(next);
                setCommit(commitSourceId, commitMessage, next);
              }}
            >
              I reviewed the diff and validation results.
            </ReviewChoiceList>
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
            <div>
              <span>Reviewed commit</span>
              <CommitChoiceList
                commits={commits.map((run) => ({
                  id: run.id,
                  title: String(
                    (run.metadata?.git_commit as { commit?: string })?.commit ??
                      run.id,
                  ).slice(0, 12),
                  detail: run.executor_type,
                }))}
                value={publishSourceId}
                disabled={busy}
                onChange={(id) => {
                  setPublishSourceId(id);
                  setPublishApproved(false);
                  setPublish(id, publishTitle, publishBody, false);
                }}
              />
            </div>
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
            <PublicationChoiceList
              checked={publishApproved}
              disabled={!preview.data || !!preview.data.blocked_reason || busy}
              onChange={(next) => {
                setPublishApproved(next);
                setPublish(publishSourceId, publishTitle, publishBody, next);
              }}
            >
              I approve publishing this commit and PR text to the GitHub
              repository shown above.
            </PublicationChoiceList>
          </details>
        )}
        {value.action === "runtime.load" && (
          <details open className="assistant-coding-scope">
            <summary>Owned llama.cpp load</summary>
            <p className="muted">
              Loads a discovered GGUF into an AI Station-owned runtime. External
              Ollama or ComfyUI processes are not stopped. The model cannot
              choose a file or GPUs.
            </p>
            <ErrorNotice error={catalog.error ?? hardware.error} />
            <div>
              <span>GGUF model</span>
              <GgufChoiceList
                models={catalog.data?.models ?? []}
                value={value.load?.model_file_id ?? ""}
                disabled={busy}
                onChange={(id) => setLoad(id, selectedLoadGpus, loadContext)}
              />
            </div>
            {!catalog.isPending && !catalog.data?.models.length && (
              <p className="notice">
                No language-model GGUFs are discovered yet. Scan model folders
                in Models first.
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
              <small>
                No cards selected uses CPU. Several cards split layers.
              </small>
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
              Stops only the selected AI Station-owned instance after its
              consumers finish. External runtimes are not touched.
            </p>
            <ErrorNotice error={catalog.error} />
            <div>
              <span>Runtime</span>
              <RuntimeChoiceList
                instances={ownedInstances}
                value={value.stop?.instance_id ?? ""}
                disabled={busy}
                onChange={setStop}
              />
            </div>
            {!ownedInstances.length && (
              <p className="notice">
                No owned llama.cpp instance is loaded. External servers cannot
                be unloaded here.
              </p>
            )}
          </details>
        )}
        {codingTask && (
          <details open className="assistant-coding-scope">
            <summary>Coding scope</summary>
            <div>
              <span>Project</span>
              <ProjectChoiceList
                projects={projects.data ?? []}
                value={projectId}
                disabled={busy}
                onChange={(id) => {
                  setProjectId(id);
                  setExternal(false);
                  setCodingModel("");
                  scope(
                    id,
                    files,
                    false,
                    value.action,
                    explore,
                    repairAttempts,
                    "",
                  );
                }}
              />
            </div>
            {externalCoding && (
              <div>
                <span>Model</span>
                <CodingModelChoiceList
                  models={codingCatalog.data?.models ?? []}
                  value={codingModel}
                  disabled={busy}
                  onChange={(id) => {
                    setCodingModel(id);
                    scope(
                      projectId,
                      files,
                      external,
                      value.action,
                      explore,
                      repairAttempts,
                      id,
                    );
                  }}
                />
                <ErrorNotice error={codingCatalog.error} />
                {codingCatalog.data?.notice && (
                  <small className="muted">{codingCatalog.data.notice}</small>
                )}
              </div>
            )}
            <ExploreChoiceList
              checked={explore}
              disabled={busy}
              onChange={(next) => {
                setExplore(next);
                setExternal(false);
                scope(projectId, files, false, value.action, next);
              }}
            >
              {value.action === "coding.local"
                ? "Let Local AI find the relevant files"
                : "Let the agent find the relevant files"}
            </ExploreChoiceList>
            {value.action === "coding.local" && explore && (
              <small>
                Public URLs in the task are fetched automatically. Local AI may
                GET further public pages and, when the Host Runner has search
                configured, query the public web. Private and loopback addresses
                are blocked. JavaScript is not executed; this is not a browser.
              </small>
            )}
            {value.action === "coding.local" && (
              <div>
                <span>Automatic repair</span>
                <RepairChoiceList
                  value={repairAttempts}
                  disabled={busy}
                  onChange={(attempts) => {
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
                />
              </div>
            )}
            {explore ? (
              <p className="muted">
                {value.action === "coding.local"
                  ? "Local source exploration in a new worktree. Review selected files and changes in the resulting Run."
                  : "Repository exploration in a new worktree. Cursor and Codex stay repository-only; they do not GET public pages."}
              </p>
            ) : (
              <FileChoiceList
                files={files}
                label="Selected files"
                onChange={(value) => {
                  setFiles(value);
                  setExternal(false);
                  scope(projectId, value, false);
                }}
              />
            )}
            {value.action === "coding.local" ? (
              <label>
                Coding model
                <select
                  value={localCodingAuto ? "auto" : "conversation"}
                  disabled={busy}
                  onChange={(event) => {
                    const automatic = event.target.value === "auto";
                    setLocalCodingAuto(automatic);
                    scope(
                      projectId,
                      files,
                      false,
                      value.action,
                      explore,
                      repairAttempts,
                      codingModel,
                      automatic,
                    );
                  }}
                >
                  <option value="auto">
                    Auto · local model with 100k+ context
                  </option>
                  <option value="conversation">
                    Use the conversation model
                  </option>
                </select>
                <small className="muted">
                  Changes stay in an isolated worktree. Review the diff and
                  validation before committing.
                </small>
              </label>
            ) : (
              <ConsentChoiceList
                checked={external}
                disabled={busy}
                onChange={(next) => {
                  setExternal(next);
                  scope(projectId, files, next);
                }}
              >
                Allow sending this instruction, project guidance and{" "}
                {explore
                  ? "relevant source files found by the agent"
                  : "the selected files"}{" "}
                to external{" "}
                {value.action === "coding.codex" ? "Codex" : "Cursor"}.
              </ConsentChoiceList>
            )}
            <ErrorNotice error={projects.error} />
          </details>
        )}
        <ErrorNotice error={error} />
      </fieldset>
      {recordingInput && (
        <div className="assistant-recording-toolbar">
          <RecordingButton
            disabled={busy}
            onBusy={onUploading}
            onRecorded={(file) => attachAudio(file, true)}
          />
        </div>
      )}
    </>
  );
}
