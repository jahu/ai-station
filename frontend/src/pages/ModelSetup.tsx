import { useId, useRef, useState, useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  Check,
  Download,
  Cpu,
  HardDrive,
  ArrowRight,
  ShieldCheck,
  RotateCcw,
  Square,
  MessageSquare,
  Image,
  Video,
  Mic,
  Music,
  UserRound,
  Brain,
  AudioLines,
} from "lucide-react";
import { api } from "../api";
import { Button } from "../components/ui/button";
import { ErrorNotice, Loading, Badge } from "../components/common";
import { randomId } from "../lib/random-id";
import type { Run } from "../api";
import RuntimeSetupPanel from "./RuntimeSetupPanel";
import SpeechSetupPanel from "./SpeechSetupPanel";
import ImageSetupPanel from "./ImageSetupPanel";
import MemorySetupPanel from "./MemorySetupPanel";
import MusicSetupPanel from "./MusicSetupPanel";
import VideoSetupPanel from "./VideoSetupPanel";
import AvatarSetupPanel from "./AvatarSetupPanel";
import EffectsSetupPanel from "./EffectsSetupPanel";
import FishSetupPanel from "./FishSetupPanel";
import ModelManagement from "./ModelManagement";
import "./ModelSetup.css";

type Entry = {
  id: string;
  name: string;
  quantization: string;
  starter?: boolean;
  trained_context?: number;
  description?: string;
  runtime_profile?: string;
  filename: string;
  file: { size_bytes: number; sha256: string };
  license: string;
  license_url: string;
  source_url: string;
  revision: string;
  manifest_sha256: string;
  model_file_id: string | null;
  definition_id?: string | null;
  ready_to_try: boolean;
  recommendation: {
    fits: boolean;
    reason: string;
    gpus: number[];
    context_size: number | null;
    ram_mib?: number;
  };
};
type Catalog = {
  can_prepare: boolean;
  engine_profile?: string | null;
  platform_notice?: string;
  entries: Entry[];
  hardware: {
    host?: { system: string; architecture: string } | null;
    memory?: { total_mib?: number } | null;
    gpus: { index: number; name?: string; memory_total_mib?: number }[];
  };
  storage?: {
    free_bytes: number;
    total_bytes: number;
    headroom_bytes: number;
  } | null;
};
export type Preparation = {
  id: string;
  entry: Pick<Entry, "name" | "file" | "quantization"> & {
    capability?: string;
  };
  definition_id?: string | null;
  attempt: number;
  run: Run;
  model_key: string | null;
  resume_allowed: boolean;
  progress: {
    phase?: string;
    engine_run_id?: string;
    received_bytes?: number;
    expected_bytes?: number;
    ready_to_try?: boolean;
    runtime_image_present?: boolean;
  };
};
const terminal = new Set(["succeeded", "failed", "canceled", "interrupted"]);
const json = (value: unknown) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(value),
});
function size(bytes: number) {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GiB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MiB`;
  return `${Math.max(0, bytes / 1024).toFixed(1)} KiB`;
}

function PreparedModel({
  model,
  onOpen,
  opening,
}: {
  model: string;
  onOpen: (model: string) => void;
  opening: boolean;
}) {
  return (
    <Button onClick={() => onOpen(model)} disabled={opening}>
      <ArrowRight size={16} />
      Open Chat with this model
    </Button>
  );
}
export function PreparationCard({
  value,
  canPrepare,
  refresh,
  onOpen,
  opening,
}: {
  value: Preparation;
  canPrepare: boolean;
  refresh: () => void;
  onOpen: (model: string) => void;
  opening: boolean;
}) {
  const active = !terminal.has(value.run.status);
  const receipt = useRef<{ run: string; id: string } | null>(null);
  const action = useMutation({
    mutationFn: (kind: "cancel" | "resume") => {
      if (!receipt.current || receipt.current.run !== value.run.id)
        receipt.current = { run: value.run.id, id: randomId() };
      return api(
        `/setup/downloads/${value.id}/${kind}`,
        json(
          kind === "resume"
            ? {
                client_request_id: receipt.current.id,
                expected_run_id: value.run.id,
              }
            : {},
        ),
      );
    },
    onSuccess: refresh,
  });
  const expected = value.progress.expected_bytes ?? value.entry.file.size_bytes;
  const received = Math.max(
    0,
    Math.min(expected, value.progress.received_bytes ?? 0),
  );
  const phase = value.progress.phase;
  const label =
    value.run.status === "succeeded"
      ? "Files verified"
      : value.run.status === "canceled"
        ? "Stopped · downloaded bytes are retained"
        : value.run.status === "failed" || value.run.status === "interrupted"
          ? "Preparation needs attention"
          : phase === "preparing_image_engine" ||
              phase === "preparing_video_engine" ||
              phase === "preparing_speech_engine" ||
              phase === "preparing_music_engine" ||
              phase === "preparing_avatar_engine"
            ? `Preparing ${phase.split("_")[1]} engine and companions`
            : phase === "checking_avatar_engine"
              ? "Checking installed avatar files"
              : phase === "verifying"
                ? "Checking the complete file"
                : phase === "inspecting"
                  ? "Checking the model and runtime"
                  : phase === "waiting_for_existing_transfer"
                    ? "Waiting for another transfer"
                    : value.run.status === "queued"
                      ? "Queued"
                      : "Downloading model";
  return (
    <article
      className="panel setup-download"
      id={`preparation-${value.id}`}
      tabIndex={-1}
      aria-label={`Model preparation ${value.id.slice(0, 8)}`}
    >
      <div className="row spread">
        <strong>{value.entry.name}</strong>
        <Badge status={value.run.status} />
      </div>
      <div className="setup-small muted">
        {value.entry.quantization} · {size(expected)} · attempt {value.attempt}
      </div>
      <p>{label}</p>
      {active && (
        <>
          <progress
            aria-label={`Download progress ${value.id.slice(0, 8)}`}
            max={expected}
            value={received}
          />
          <p className="setup-small muted">
            {size(received)} of {size(expected)} downloaded
            {phase === "verifying" || phase === "inspecting"
              ? " · verification is still running"
              : ""}
          </p>
        </>
      )}
      {value.run.error_message && (
        <p className="notice" role="alert">
          {value.run.error_message}
        </p>
      )}
      <ErrorNotice error={action.error} />
      {value.run.status === "succeeded" && !value.progress.ready_to_try && (
        <p className="notice">
          Your files are safe. Compatible runtime or hardware setup is still
          needed before this model can run.
        </p>
      )}
      <div className="row">
        {active && canPrepare && (
          <Button
            variant="secondary"
            disabled={
              action.isPending || value.run.status === "cancel_requested"
            }
            onClick={() => action.mutate("cancel")}
          >
            <Square size={14} />
            Stop
          </Button>
        )}
        {value.resume_allowed && canPrepare && (
          <Button
            variant="secondary"
            disabled={action.isPending}
            onClick={() => action.mutate("resume")}
          >
            <RotateCcw size={14} />
            Resume preparation
          </Button>
        )}
        {value.entry.capability === "embedding" &&
          value.definition_id &&
          value.progress.ready_to_try && (
            <Link
              className="text-link"
              to={`/memory?embedding_model=${value.definition_id}`}
            >
              Choose this encoder in Memory →
            </Link>
          )}
        {value.entry.capability === "music" &&
          value.definition_id &&
          value.progress.ready_to_try && (
            <Link
              className="text-link"
              to={`/audio?mode=music&model=${value.definition_id}`}
            >
              Create with this music model →
            </Link>
          )}
        {value.entry.capability === "speech" &&
          value.definition_id &&
          value.progress.ready_to_try && (
            <Link
              className="text-link"
              to={`/audio?model=${value.definition_id}`}
            >
              Open Audio with this model →
            </Link>
          )}
        {value.entry.capability === "avatar" &&
          value.definition_id &&
          value.progress.ready_to_try && (
            <Link
              className="text-link"
              to={`/avatars?model=${value.definition_id}`}
            >
              Open Avatars with this model →
            </Link>
          )}
        {value.entry.capability === "video" &&
          value.definition_id &&
          value.progress.ready_to_try && (
            <Link
              className="text-link"
              to={`/video?model=${value.definition_id}`}
            >
              Open Video with this model →
            </Link>
          )}
        {value.entry.capability === "image" &&
          value.definition_id &&
          value.progress.ready_to_try && (
            <Link
              className="text-link"
              to={`/images?model=${value.definition_id}`}
            >
              Open Images with this model →
            </Link>
          )}
        {value.model_key && value.progress.ready_to_try && (
          <PreparedModel
            model={value.model_key}
            onOpen={onOpen}
            opening={opening}
          />
        )}
        {value.progress.engine_run_id && (
          <Link
            className="text-link"
            to={`/runs/${value.progress.engine_run_id}`}
          >
            Engine setup & logs
          </Link>
        )}
        <Link className="text-link" to={`/runs/${value.run.id}`}>
          Details & logs
        </Link>
      </div>
    </article>
  );
}

const setupCapabilities = [
  ["chat", "Conversation", MessageSquare],
  ["images", "Images", Image],
  ["video", "Video", Video],
  ["speech", "Voice", Mic],
  ["music", "Music", Music],
  ["avatar", "Avatars", UserRound],
  ["memory", "Memory", Brain],
  ["effects", "Sound effects", AudioLines],
] as const;

export default function ModelSetup() {
  const [params] = useSearchParams();
  const requestedCapability = params.get("capability") ?? "chat";
  const selectedCapability =
    requestedCapability === "fish"
      ? "speech"
      : setupCapabilities.some(([key]) => key === requestedCapability)
        ? requestedCapability
        : "chat";
  const navigate = useNavigate(),
    cache = useQueryClient();
  const catalog = useQuery({
    queryKey: ["setup-catalog"],
    queryFn: () => api<Catalog>("/setup/catalog"),
  });
  const history = useQuery({
    queryKey: ["model-preparations"],
    queryFn: () => api<Preparation[]>("/setup/downloads"),
    refetchInterval: (query) =>
      query.state.data?.some((row) => !terminal.has(row.run.status))
        ? 1000
        : false,
  });
  const [selected, setSelected] = useState("");
  const [accepted, setAccepted] = useState("");
  const [downloadOnly, setDownloadOnly] = useState(false);
  const [moreModels, setMoreModels] = useState(false);
  const [modelSearch, setModelSearch] = useState("");
  const [onlyFitting, setOnlyFitting] = useState(false);
  const [runtimeReady, setRuntimeReady] = useState<boolean | undefined>(
    undefined,
  );
  const entries = catalog.data?.entries ?? [];
  const query = modelSearch.trim().toLocaleLowerCase();
  const visibleEntries = entries.filter(
    (entry) =>
      (!moreModels ||
        ((!onlyFitting || entry.recommendation.fits) &&
          `${entry.name} ${entry.quantization}`
            .toLocaleLowerCase()
            .includes(query))) &&
      (moreModels || entry.starter !== false),
  );
  const current =
    entries.find((row) => row.id === selected) ??
    entries.find((row) => row.recommendation.fits) ??
    entries.find((row) => row.starter !== false) ??
    entries[0];
  const existingPreparation = history.data?.find(
    (row) =>
      row.entry.file.sha256 === current?.file.sha256 &&
      (!terminal.has(row.run.status) || row.resume_allowed),
  );
  const storage = catalog.data?.storage;
  const insufficientStorage = Boolean(
    current &&
    storage &&
    storage.free_bytes < current.file.size_bytes + storage.headroom_bytes,
  );
  const token = useRef<{ manifest: string; id: string } | null>(null);
  const completed = useRef(new Set<string>());
  const licenseId = useId();
  const refresh = () => {
    void cache.invalidateQueries({ queryKey: ["model-preparations"] });
    void cache.invalidateQueries({ queryKey: ["setup-catalog"] });
  };
  useEffect(() => {
    for (const row of history.data ?? [])
      if (
        row.run.status === "succeeded" &&
        !completed.current.has(row.run.id)
      ) {
        completed.current.add(row.run.id);
        void cache.invalidateQueries({ queryKey: ["setup-catalog"] });
        void cache.invalidateQueries({ queryKey: ["chat-model-catalog"] });
        void cache.invalidateQueries({ queryKey: ["models"] });
      }
  }, [history.data, cache]);
  const download = useMutation({
    mutationFn: () => {
      if (!current || accepted !== current.manifest_sha256)
        throw new Error("Review the model license before downloading.");
      const identity = `${current.manifest_sha256}:${downloadOnly}`;
      if (!token.current || token.current.manifest !== identity)
        token.current = { manifest: identity, id: randomId() };
      return api<Preparation>(
        "/setup/downloads",
        json({
          client_request_id: token.current.id,
          catalog_id: current.id,
          manifest_sha256: current.manifest_sha256,
          license_accepted: true,
          download_only: downloadOnly,
        }),
      );
    },
    onSuccess: refresh,
  });
  const [verificationId, setVerificationId] = useState<string | null>(null);
  const verify = useMutation({
    mutationFn: () =>
      api<Run>(
        `/models/definitions/${current?.definition_id}/install`,
        json({}),
      ),
    onSuccess: (run) => setVerificationId(run.id),
  });
  const verification = useQuery({
    queryKey: ["setup-model-verification", verificationId],
    queryFn: () => api<Run>(`/runs/${verificationId}`),
    enabled: Boolean(verificationId),
    refetchInterval: (query) =>
      terminal.has(query.state.data?.status ?? "") ? false : 1000,
  });
  useEffect(() => {
    if (verification.data && terminal.has(verification.data.status)) {
      void cache.invalidateQueries({ queryKey: ["setup-catalog"] });
      void cache.invalidateQueries({ queryKey: ["models"] });
      void cache.invalidateQueries({ queryKey: ["chat-model-catalog"] });
    }
  }, [verification.data, cache]);
  const verifying =
    verify.isPending ||
    Boolean(verificationId && !terminal.has(verification.data?.status ?? ""));
  const chat = useMutation({
    mutationFn: (model: string) =>
      api<{ id: string }>(
        "/chat/conversations",
        json({ model, execution_mode: "assistant" }),
      ),
    onSuccess: (row) => navigate(`/chat/${row.id}`),
  });
  return (
    <>
      <ModelManagement current="setup" title="Quick setup">
        Pick what you want to do. We guide you through installing a supported
        model and the engine it needs, with a hardware check before downloading.
      </ModelManagement>
      <h2 className="model-setup-question">What would you like to create?</h2>
      <nav className="model-capability-choices" aria-label="Setup category">
        {setupCapabilities.map(([key, label, Icon]) => (
          <Link
            key={key}
            to={`/setup/models?capability=${key}`}
            aria-current={selectedCapability === key ? "page" : undefined}
          >
            <Icon size={18} />
            {label}
          </Link>
        ))}
      </nav>
      {catalog.data?.platform_notice && (
        <p className="notice">{catalog.data.platform_notice}</p>
      )}
      <div className="setup-machine panel" aria-label="Detected workstation">
        <Cpu size={20} />
        <div>
          <strong>Your workstation</strong>
          <p className="muted">
            {catalog.isPending
              ? "Detecting your workstation…"
              : catalog.data?.hardware.memory?.total_mib
                ? `${Math.round(catalog.data.hardware.memory.total_mib / 1024)} GiB RAM`
                : "Hardware inspection unavailable"}
            {catalog.data?.hardware.host?.system === "Darwin" && (
              <span>
                {" "}
                · Mac{" "}
                {catalog.data.hardware.host.architecture === "arm64"
                  ? "Apple Silicon"
                  : "Intel"}
              </span>
            )}
            {catalog.data?.hardware.gpus.map((gpu) => (
              <span key={gpu.index}>
                {" "}
                · {gpu.name ?? `GPU ${gpu.index}`}{" "}
                {gpu.memory_total_mib
                  ? `(${Math.round(gpu.memory_total_mib / 1024)} GiB)`
                  : ""}
              </span>
            ))}
          </p>
          <p className="setup-small muted">
            {storage
              ? `${size(storage.free_bytes)} free in AI Station storage`
              : "Available storage will be checked before downloading."}
          </p>
        </div>
      </div>
      <ErrorNotice
        error={
          catalog.error ??
          history.error ??
          download.error ??
          chat.error ??
          verify.error ??
          verification.error
        }
      />
      {selectedCapability === "chat" && (
        <>
          {catalog.data && !catalog.data.platform_notice && (
            <RuntimeSetupPanel
              key={
                current?.runtime_profile ??
                catalog.data.engine_profile ??
                "cuda"
              }
              profile={
                current?.runtime_profile ??
                catalog.data.engine_profile ??
                undefined
              }
              onReadiness={setRuntimeReady}
            />
          )}
          {catalog.isPending ? (
            <Loading />
          ) : (
            <div className="setup-layout">
              <section
                className="setup-choices"
                aria-label="Conversation model choices"
              >
                <h2>Start with a conversation model</h2>
                <p className="muted">
                  Start small, or explore larger models. Each choice runs
                  locally with llama.cpp and shows an estimate for your
                  hardware.
                </p>
                {entries.some((entry) => entry.starter === false) && (
                  <div className="setup-explore">
                    <Button
                      variant="secondary"
                      aria-expanded={moreModels}
                      aria-controls="setup-model-options"
                      onClick={() => setMoreModels(!moreModels)}
                    >
                      {moreModels
                        ? "Show starter models"
                        : "Explore larger models"}
                    </Button>
                    {moreModels && (
                      <div className="setup-catalog-filters">
                        <label>
                          Search model or quantization
                          <input
                            type="search"
                            placeholder="Try 14B or Q8_0"
                            value={modelSearch}
                            onChange={(event) =>
                              setModelSearch(event.target.value)
                            }
                          />
                        </label>
                        <label className="setup-license">
                          <input
                            type="checkbox"
                            checked={onlyFitting}
                            onChange={(event) =>
                              setOnlyFitting(event.target.checked)
                            }
                          />
                          <span>Only models that fit this workstation</span>
                        </label>
                        <p className="setup-small muted" role="status">
                          {visibleEntries.length} of {entries.length} reviewed
                          profiles. Search stays on this station.
                        </p>
                      </div>
                    )}
                  </div>
                )}
                {!catalog.data?.can_prepare && (
                  <p className="notice">
                    Your administrator manages shared model installation. You
                    can use models already available in Chat.
                  </p>
                )}
                <div className="setup-options" id="setup-model-options">
                  {visibleEntries.length === 0 && (
                    <p className="notice">
                      No matching profiles. Try another search or clear the fit
                      filter.
                    </p>
                  )}
                  {visibleEntries.map((entry) => (
                    <label
                      key={entry.id}
                      className={`panel setup-option ${current?.id === entry.id ? "selected" : ""}`}
                    >
                      <input
                        type="radio"
                        name="setup-model"
                        value={entry.id}
                        checked={current?.id === entry.id}
                        onChange={() => {
                          setSelected(entry.id);
                          setAccepted("");
                          setDownloadOnly(false);
                        }}
                        aria-label={`Choose ${entry.starter === false ? `${entry.name} ` : ""}${entry.quantization}`}
                      />
                      <div>
                        <div className="row spread">
                          <strong>
                            {entry.runtime_profile
                              ? "CPU · small conversation model"
                              : entry.starter === false
                                ? entry.name
                                : entry.quantization === "Q4_K_M"
                                  ? "Balanced"
                                  : "Higher precision"}
                          </strong>
                          {entry.recommendation.fits && (
                            <span className="setup-fit">
                              <Check size={14} />
                              Estimated fit
                            </span>
                          )}
                        </div>
                        <p>
                          {entry.starter === false
                            ? `Up to ${entry.trained_context?.toLocaleString()} model context · llama.cpp`
                            : entry.name}
                        </p>
                        {entry.description && (
                          <p className="setup-small muted">
                            {entry.description}
                          </p>
                        )}
                        <div className="setup-small setup-size muted">
                          {entry.quantization} · <HardDrive size={13} />{" "}
                          {size(entry.file.size_bytes)} download
                        </div>
                        <p className="setup-small muted">
                          {entry.recommendation.reason}
                        </p>
                        {entry.runtime_profile &&
                          entry.recommendation.ram_mib && (
                            <p className="setup-small muted">
                              {size(entry.recommendation.ram_mib * 1024 ** 2)}{" "}
                              system RAM reserved while the model is loaded.
                            </p>
                          )}
                        {entry.model_file_id && (
                          <span className="chip">Files already installed</span>
                        )}
                      </div>
                    </label>
                  ))}
                </div>
                {current && (
                  <div className="panel setup-confirm">
                    <h3>
                      <ShieldCheck size={18} /> Your download
                    </h3>
                    <p>
                      <strong>
                        {current.name} · {current.quantization}
                      </strong>
                    </p>
                    <p>
                      {size(current.file.size_bytes)} · {current.license} model
                      license
                    </p>
                    <p className="muted">
                      Weights stay on this station. No cloud account is needed.
                      Existing models and files are kept.
                    </p>
                    <details>
                      <summary>Model source and technical details</summary>
                      <p>
                        <a
                          href={current.source_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Publisher and model files
                        </a>{" "}
                        ·{" "}
                        <a
                          href={current.license_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Read model license
                        </a>
                      </p>
                      <p className="setup-small model-path">
                        Revision: {current.revision}
                        <br />
                        SHA-256: {current.file.sha256}
                      </p>
                      {current.recommendation.context_size && (
                        <p className="muted">
                          Suggested context:{" "}
                          {current.recommendation.context_size.toLocaleString()}{" "}
                          tokens ·{" "}
                          {current.runtime_profile
                            ? "CPU"
                            : `GPU ${current.recommendation.gpus.join(", ")}`}
                          . The actual model is checked again before loading.
                        </p>
                      )}
                    </details>
                    {!current.model_file_id && existingPreparation && (
                      <Button
                        variant="secondary"
                        onClick={() => {
                          const card = document.getElementById(
                            `preparation-${existingPreparation.id}`,
                          );
                          card?.scrollIntoView?.({
                            behavior: "smooth",
                            block: "nearest",
                          });
                          card?.focus({ preventScroll: true });
                        }}
                      >
                        View existing preparation
                        <ArrowRight size={16} />
                      </Button>
                    )}
                    {!current.model_file_id && !existingPreparation && (
                      <>
                        {insufficientStorage && (
                          <p className="notice" role="alert">
                            More free AI Station storage is needed for this
                            download and its safety headroom. Existing files are
                            kept.
                          </p>
                        )}
                        {(!current.recommendation.fits ||
                          runtimeReady === false) && (
                          <label className="setup-license">
                            <input
                              type="checkbox"
                              checked={downloadOnly}
                              onChange={(e) =>
                                setDownloadOnly(e.target.checked)
                              }
                              disabled={
                                !catalog.data?.can_prepare || download.isPending
                              }
                            />
                            <span>
                              Download files only. Runtime or hardware setup is
                              still needed before this profile can run.
                            </span>
                          </label>
                        )}
                        <label className="setup-license" htmlFor={licenseId}>
                          <input
                            id={licenseId}
                            type="checkbox"
                            checked={accepted === current.manifest_sha256}
                            disabled={
                              !catalog.data?.can_prepare || download.isPending
                            }
                            onChange={(event) =>
                              setAccepted(
                                event.target.checked
                                  ? current.manifest_sha256
                                  : "",
                              )
                            }
                          />
                          <span>
                            I have reviewed the{" "}
                            <a
                              href={current.license_url}
                              target="_blank"
                              rel="noreferrer"
                            >
                              model license
                            </a>{" "}
                            and want to download these files.
                          </span>
                        </label>
                        <Button
                          disabled={
                            !catalog.data?.can_prepare ||
                            insufficientStorage ||
                            download.isPending ||
                            accepted !== current.manifest_sha256 ||
                            ((!current.recommendation.fits ||
                              runtimeReady === false) &&
                              !downloadOnly)
                          }
                          onClick={() => download.mutate()}
                        >
                          <Download size={16} />
                          {download.isPending
                            ? "Queuing…"
                            : `Download ${size(current.file.size_bytes)}`}
                        </Button>
                      </>
                    )}
                    {current.model_file_id && !current.ready_to_try && (
                      <>
                        <p className="notice">
                          Model files are installed. Compatible runtime and
                          hardware readiness still need to be checked before
                          trying this model.
                        </p>
                        {current.definition_id && catalog.data?.can_prepare && (
                          <Button
                            variant="secondary"
                            disabled={verifying}
                            onClick={() => verify.mutate()}
                          >
                            {verifying
                              ? "Checking readiness…"
                              : "Verify model readiness"}
                          </Button>
                        )}
                        {verification.data?.error_message && (
                          <p className="notice" role="alert">
                            {verification.data.error_message}
                          </p>
                        )}
                      </>
                    )}
                    {current.model_file_id && current.ready_to_try && (
                      <PreparedModel
                        model={`llamacpp:${current.model_file_id}`}
                        onOpen={(model) => chat.mutate(model)}
                        opening={chat.isPending}
                      />
                    )}
                  </div>
                )}
              </section>
              <section
                className="setup-history"
                aria-label="Model preparation history"
              >
                <h2>Your preparations</h2>
                <p className="muted">
                  You can leave this page. Progress is saved; stopped transfers
                  resume from their verified file identity.
                </p>
                {history.isPending ? (
                  <Loading />
                ) : (
                  !history.data?.length && (
                    <div className="panel setup-empty">
                      <Download size={24} />
                      <p>Your downloads will appear here.</p>
                      <small className="muted">
                        Conversation model downloads are saved here. Other
                        installations keep their progress in their own setup
                        cards.
                      </small>
                    </div>
                  )
                )}
                {history.data?.map((row) => (
                  <PreparationCard
                    key={row.id}
                    value={row}
                    canPrepare={catalog.data?.can_prepare ?? false}
                    refresh={refresh}
                    onOpen={(model) => chat.mutate(model)}
                    opening={chat.isPending}
                  />
                ))}
              </section>
            </div>
          )}
        </>
      )}
      {selectedCapability !== "chat" && (
        <section
          className="setup-additional"
          aria-label="Capability setup"
          data-model-category-panel
        >
          {selectedCapability === "speech" && (
            <>
              <SpeechSetupPanel />
              <FishSetupPanel />
            </>
          )}
          {selectedCapability === "images" && <ImageSetupPanel />}
          {selectedCapability === "video" && <VideoSetupPanel />}
          {selectedCapability === "avatar" && <AvatarSetupPanel />}
          {selectedCapability === "effects" && <EffectsSetupPanel />}
          {selectedCapability === "music" && <MusicSetupPanel />}
          {selectedCapability === "memory" && <MemorySetupPanel />}
        </section>
      )}
    </>
  );
}
