import { useId, useRef, useState, useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import {
  Check,
  Download,
  Cpu,
  HardDrive,
  ArrowRight,
  ShieldCheck,
  RotateCcw,
  Square,
} from "lucide-react";
import { api } from "../api";
import { Button } from "../components/ui/button";
import { ErrorNotice, Loading, PageTitle, Badge } from "../components/common";
import { randomId } from "../lib/random-id";
import type { Run } from "../api";
import RuntimeSetupPanel from "./RuntimeSetupPanel";
import SpeechSetupPanel from "./SpeechSetupPanel";
import "./ModelSetup.css";

type Entry = {
  id: string;
  name: string;
  quantization: string;
  starter?: boolean;
  trained_context?: number;
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
  };
};
type Catalog = {
  can_prepare: boolean;
  entries: Entry[];
  hardware: {
    memory?: { total_mib?: number } | null;
    gpus: { index: number; name?: string; memory_total_mib?: number }[];
  };
  storage?: {
    free_bytes: number;
    total_bytes: number;
    headroom_bytes: number;
  } | null;
};
type Preparation = {
  id: string;
  entry: Entry;
  attempt: number;
  run: Run;
  model_key: string | null;
  resume_allowed: boolean;
  progress: {
    phase?: string;
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
function PreparationCard({
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
        {value.model_key && value.progress.ready_to_try && (
          <PreparedModel
            model={value.model_key}
            onOpen={onOpen}
            opening={opening}
          />
        )}
        <Link className="text-link" to={`/runs/${value.run.id}`}>
          Details & logs
        </Link>
      </div>
    </article>
  );
}

export default function ModelSetup() {
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
      <PageTitle eyebrow="GET STARTED / MODELS" title="Set up your models">
        Start with a local conversation model or add a voice. AI Station
        downloads, checks and prepares the files for you.
      </PageTitle>
      <RuntimeSetupPanel onReadiness={setRuntimeReady} />
      <SpeechSetupPanel />
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
        <Link to="/models" className="text-link">
          Use existing models
        </Link>
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
              Start small, or explore larger models. Each choice runs locally
              with llama.cpp and shows an estimate for your hardware.
            </p>
            {entries.some((entry) => entry.starter === false) && (
              <div className="setup-explore">
                <Button
                  variant="secondary"
                  aria-expanded={moreModels}
                  aria-controls="setup-model-options"
                  onClick={() => setMoreModels(!moreModels)}
                >
                  {moreModels ? "Show starter models" : "Explore larger models"}
                </Button>
                {moreModels && (
                  <div className="setup-catalog-filters">
                    <label>
                      Search model or quantization
                      <input
                        type="search"
                        placeholder="Try 14B or Q8_0"
                        value={modelSearch}
                        onChange={(event) => setModelSearch(event.target.value)}
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
                Your administrator manages shared model installation. You can
                use models already available in Chat.
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
                        {entry.starter === false
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
                    <div className="setup-small setup-size muted">
                      {entry.quantization} · <HardDrive size={13} />{" "}
                      {size(entry.file.size_bytes)} download
                    </div>
                    <p className="setup-small muted">
                      {entry.recommendation.reason}
                    </p>
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
                      tokens · GPU {current.recommendation.gpus.join(", ")}. The
                      actual model is checked again before loading.
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
                        More free AI Station storage is needed for this download
                        and its safety headroom. Existing files are kept.
                      </p>
                    )}
                    {(!current.recommendation.fits ||
                      runtimeReady === false) && (
                      <label className="setup-license">
                        <input
                          type="checkbox"
                          checked={downloadOnly}
                          onChange={(e) => setDownloadOnly(e.target.checked)}
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
                            event.target.checked ? current.manifest_sha256 : "",
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
                      Model files are installed. Compatible runtime and hardware
                      readiness still need to be checked before trying this
                      model.
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
                    Conversation model downloads are saved here. Speech setup
                    keeps its own progress above.
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
  );
}
