import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Box, RefreshCw } from "lucide-react";
import { api, useHardware, type Run } from "../api";
import { useAccount } from "../account-context";
import {
  Badge,
  Empty,
  ErrorNotice,
  Loading,
  PageTitle,
} from "../components/common";
import { Button } from "../components/ui/button";
import { useListKeyboard } from "./useListKeyboard";
import { GpuChoiceList } from "./GpuChoiceList";

interface Compatibility {
  format: string;
  category: string;
  runtime: string | null;
  adapter: string;
  operational: boolean;
  summary: string;
}
interface Preset {
  gpus: number[];
  context_size: number;
  cache_type: "f16" | "q8_0";
}
interface Definition {
  image_backend?: "qwen" | "krea2";
  id: string;
  name: string;
  family: string;
  category: string;
  file_id: string | null;
  capabilities: string[];
  status: string;
  last_verify_run_id: string | null;
  preset: Preset;
  compatibility: Compatibility | null;
  file: {
    id: string;
    filename: string;
    host_path: string | null;
    relative_path?: string;
    format: string;
    category: string;
    availability: string;
    size_bytes: number;
  } | null;
}
interface ModelFile {
  id: string;
  filename: string;
  host_path: string | null;
  relative_path?: string;
  root_label: string;
  category: string;
  format: string;
  size_bytes: number;
  family: string;
  quantization: string;
  capabilities: string[];
  availability: string;
  discovered_at: string;
  last_seen_at: string | null;
  last_scan_run_id: string | null;
  definitions?: Definition[];
}
interface Inventory {
  items: ModelFile[];
  total: number;
  latest_scan: Run | null;
}
const categories = [
  ["", "All"],
  ["llm", "LLM"],
  ["image", "Images"],
  ["video", "Video"],
  ["audio", "Audio"],
  ["other", "Other"],
];
const size = (bytes: number) =>
  bytes >= 1024 ** 3
    ? `${(bytes / 1024 ** 3).toFixed(2)} GiB`
    : `${(bytes / 1024 ** 2).toFixed(1)} MiB`;
const terminal = ["succeeded", "failed", "canceled", "interrupted"];
const json = (method: string, body: unknown) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

function ModelFileCards({ models }: { models: ModelFile[] }) {
  const headingId = useId();
  const labelId = useId();
  const { listRef, onKeyDown, itemProps } = useListKeyboard(
    models,
    (model) => model.id,
  );
  return (
    <section aria-labelledby={headingId}>
      <h2 id={headingId} className="sr-only">
        Models
      </h2>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a model while the list is focused. Enter inspects it.
      </p>
      <div
        ref={listRef}
        className="model-grid"
        aria-labelledby={labelId}
        onKeyDown={onKeyDown}
      >
        {models.map((model, i) => (
          <Link
            className="panel model-card"
            to={`/models/${model.id}`}
            key={model.id}
            aria-label={`Inspect ${model.filename} ${model.id.slice(0, 8)}`}
            {...itemProps(i, model.id)}
          >
            <div className="row">
              <Box size={20} aria-hidden="true" />
              <span className="tiny-tag">{model.format}</span>
              <span className="muted">{size(model.size_bytes)}</span>
            </div>
            <h2>{model.filename}</h2>
            <div className="row model-tags">
              <span>{model.category}</span>
              {model.quantization && <span>{model.quantization}</span>}
              <span>
                {model.availability === "present"
                  ? "Observed"
                  : model.availability === "missing"
                    ? "Not found in last scan"
                    : "Not checked"}
              </span>
            </div>
            <p className="muted model-path">
              {model.relative_path ? "AI Station storage" : model.host_path}
            </p>
            <small className="muted">
              {model.last_seen_at
                ? `Last seen ${new Date(model.last_seen_at).toLocaleString()}`
                : "No verified observation"}
            </small>
          </Link>
        ))}
      </div>
    </section>
  );
}

function DefinitionCards({ definitions }: { definitions: Definition[] }) {
  const headingId = useId();
  const labelId = useId();
  const { listRef, onKeyDown, itemProps } = useListKeyboard(
    definitions,
    (item) => item.id,
  );
  return (
    <section aria-labelledby={headingId}>
      <h2 id={headingId} className="sr-only">
        Definitions
      </h2>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a definition while the list is focused. Enter inspects
        it.
      </p>
      <div
        ref={listRef}
        className="model-grid"
        aria-labelledby={labelId}
        onKeyDown={onKeyDown}
      >
        {definitions.map((item, i) => (
          <Link
            className="panel model-card"
            to={item.file_id ? `/models/${item.file_id}` : "/models"}
            key={item.id}
            aria-label={`Inspect ${item.name} ${item.id.slice(0, 8)}`}
            {...itemProps(i, item.id)}
          >
            <div className="row">
              <Box size={20} aria-hidden="true" />
              <Badge status={item.status} />
            </div>
            <h2>{item.name}</h2>
            <p className="muted model-path">
              {item.file?.filename ?? "Linked file missing"}
            </p>
            <small className="muted">
              {item.image_backend
                ? "Image model · configure in Images"
                : item.compatibility?.operational
                  ? "Managed llama.cpp after a successful install"
                  : "Catalogued only · no managed adapter"}
            </small>
          </Link>
        ))}
      </div>
    </section>
  );
}

export function Models() {
  const account = useAccount();
  const canManage =
    account.mode === "operator" || account.user?.is_admin === true;
  const navigate = useNavigate();
  const [view, setView] = useState<"files" | "definitions">("files");
  const [category, setCategory] = useState("");
  const [q, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const params = new URLSearchParams({
    q,
    offset: String(offset),
    limit: "50",
  });
  if (category) params.set("category", category);
  const inventory = useQuery({
    queryKey: ["models", params.toString()],
    queryFn: () => api<Inventory>(`/models?${params}`),
    refetchInterval: 5000,
  });
  const definitions = useQuery({
    queryKey: ["model-definitions"],
    queryFn: () =>
      api<{ items: Definition[]; total: number }>(`/models/definitions`),
    refetchInterval: 5000,
  });
  const compatibility = useQuery({
    queryKey: ["model-compatibility"],
    queryFn: () =>
      api<{ items: Compatibility[]; note: string }>("/models/compatibility"),
  });
  const scan = useMutation({
    mutationFn: () =>
      api<Run>("/models/discover", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      }),
    onSuccess: (run) => navigate(`/runs/${run.id}`),
  });
  const latest = inventory.data?.latest_scan;
  const active = latest && !terminal.includes(latest.status);
  return (
    <>
      <PageTitle
        eyebrow="REGISTRY / INSTALLED FILES"
        title="Models"
        action={
          canManage && (
            <Button
              onClick={() => scan.mutate()}
              disabled={scan.isPending || Boolean(active)}
            >
              <RefreshCw size={16} />
              {active ? "Scan in progress" : "Discover models"}
            </Button>
          )
        }
      >
        Your existing models and saved load presets. Discovery reads host
        metadata and keeps files in place. Guided setup downloads new models
        into AI Station storage.
      </PageTitle>
      <p className="muted">
        <Link className="text-link" to="/setup/models">
          Set up a local model →
        </Link>{" "}
        · Guided downloads, hardware fit and saved progress.
      </p>
      <ErrorNotice error={inventory.error ?? definitions.error ?? scan.error} />
      <section className="panel model-toolbar">
        <div className="row model-tabs">
          <Button
            variant={view === "files" ? "default" : "secondary"}
            onClick={() => setView("files")}
          >
            Observed files
          </Button>
          <Button
            variant={view === "definitions" ? "default" : "secondary"}
            onClick={() => setView("definitions")}
          >
            Definitions
          </Button>
        </div>
        {view === "files" && (
          <>
            <div className="row model-tabs">
              {categories.map(([key, label]) => (
                <Button
                  variant={category === key ? "default" : "secondary"}
                  key={key}
                  onClick={() => {
                    setCategory(key);
                    setOffset(0);
                  }}
                >
                  {label}
                </Button>
              ))}
            </div>
            <label>
              Find model
              <input
                value={q}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setOffset(0);
                }}
                placeholder="Search filenames…"
                maxLength={200}
              />
            </label>
          </>
        )}
        {latest && (
          <div className="row">
            <Link to={`/runs/${latest.id}`}>Latest discovery Run</Link>
            <Badge status={latest.status} />
          </div>
        )}
      </section>
      {view === "files" ? (
        inventory.isPending ? (
          <Loading />
        ) : inventory.data?.items.length ? (
          <ModelFileCards models={inventory.data.items} />
        ) : (
          <section className="panel">
            <Empty title="No model files in this view">
              Use Discover models to scan the Host Runner’s configured roots, or
              adjust the filter. No models are downloaded automatically.
            </Empty>
          </section>
        )
      ) : definitions.isPending ? (
        <Loading />
      ) : definitions.data?.items.length ? (
        <DefinitionCards definitions={definitions.data.items} />
      ) : (
        <section className="panel">
          <Empty title="No curated definitions yet">
            Open an observed file and save a definition. Installation then
            verifies that local file and, for llama.cpp, an already-installed
            image.
          </Empty>
        </section>
      )}
      {view === "files" && (
        <div className="row">
          <Button
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - 50))}
          >
            Previous
          </Button>
          <span className="muted">
            {inventory.data?.total ?? 0} files · page {offset / 50 + 1}
          </span>
          <Button
            disabled={!inventory.data || offset + 50 >= inventory.data.total}
            onClick={() => setOffset(offset + 50)}
          >
            Next
          </Button>
        </div>
      )}
      <section className="panel model-card">
        <h2>Declared compatibility</h2>
        <p className="muted">
          {compatibility.data?.note ??
            "Format and category pairings with a runtime family. They do not prove a successful load."}
        </p>
        <ul className="model-compatibility">
          {(compatibility.data?.items ?? []).map((item) => (
            <li key={`${item.format}-${item.category}`}>
              <strong>
                {item.format} / {item.category}
              </strong>
              <span>
                {item.operational ? "Operational adapter" : "Observed only"} ·{" "}
                {item.runtime ?? "no runtime"}
              </span>
              <p>{item.summary}</p>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}

export function ModelDetail() {
  const account = useAccount();
  const canManage =
    account.mode === "operator" || account.user?.is_admin === true;
  const { id } = useParams();
  const navigate = useNavigate();
  const cache = useQueryClient();
  const hardware = useHardware();
  const model = useQuery({
    queryKey: ["model", id],
    queryFn: () => api<ModelFile>(`/models/${id}`),
  });
  const runtimes = useQuery({
    queryKey: ["llama-models"],
    queryFn: () =>
      api<{
        instances: {
          id: string;
          status: string;
          metadata: {
            model_file_id?: string;
            health_run_id?: string;
            health?: { status?: string; alive?: boolean; n_ctx?: number };
          };
        }[];
      }>("/llama"),
    refetchInterval: 5000,
  });
  const definition = model.data?.definitions?.[0];
  const matchingInstances =
    runtimes.data?.instances?.filter(
      (item) => item.metadata.model_file_id === id,
    ) ?? [];
  const instance =
    matchingInstances.find(
      (item) => !["stopped", "failed"].includes(item.status),
    ) ?? matchingInstances.at(-1);
  const [name, setName] = useState<string | null>(null);
  const [context, setContext] = useState<number | null>(null);
  const [cacheType, setCacheType] = useState<"f16" | "q8_0" | null>(null);
  const [gpus, setGpus] = useState<number[] | null>(null);
  const selectedGpus =
    gpus ??
    definition?.preset.gpus ??
    (hardware.data?.gpus ?? []).map((gpu) => Number(gpu.index));
  const selectedName =
    name ??
    definition?.name ??
    model.data?.filename.replace(/\.gguf$/i, "") ??
    "";
  const selectedContext = context ?? definition?.preset.context_size ?? 4096;
  const selectedCache = cacheType ?? definition?.preset.cache_type ?? "f16";
  const save = useMutation({
    mutationFn: () =>
      definition
        ? api<Definition>(
            `/models/definitions/${definition.id}`,
            json("PATCH", {
              name: selectedName,
              ...(!definition.image_backend
                ? {
                    gpus: selectedGpus,
                    context_size: selectedContext,
                    cache_type: selectedCache,
                  }
                : {}),
            }),
          )
        : api<Definition>(
            "/models/definitions",
            json("POST", {
              file_id: id,
              name: selectedName,
              gpus: selectedGpus,
              context_size: selectedContext,
              cache_type: selectedCache,
            }),
          ),
    onSuccess: () => void cache.invalidateQueries({ queryKey: ["model", id] }),
  });
  const install = useMutation({
    mutationFn: (definitionId: string) =>
      api<Run>(`/models/definitions/${definitionId}/install`, json("POST", {})),
    onSuccess: (run) => {
      void cache.invalidateQueries({ queryKey: ["model", id] });
      navigate(`/runs/${run.id}`);
    },
  });
  const load = useMutation({
    mutationFn: (definitionId: string) =>
      api<Run>(`/models/definitions/${definitionId}/load`, json("POST", {})),
    onSuccess: (run) => navigate(`/runs/${run.id}`),
  });
  const remove = useMutation({
    mutationFn: (definitionId: string) =>
      api(`/models/definitions/${definitionId}`, { method: "DELETE" }),
    onSuccess: () => void cache.invalidateQueries({ queryKey: ["model", id] }),
  });
  const health = useMutation({
    mutationFn: (instanceId: string) =>
      api<Run>(`/llama/${instanceId}/health`, json("POST", {})),
    onSuccess: (run) => {
      void cache.invalidateQueries({ queryKey: ["llama-models"] });
      navigate(`/runs/${run.id}`);
    },
  });
  const restart = useMutation({
    mutationFn: (instanceId: string) =>
      api<Run>(`/llama/${instanceId}/restart`, json("POST", {})),
    onSuccess: (run) => {
      void cache.invalidateQueries({ queryKey: ["llama-models"] });
      navigate(`/runs/${run.id}`);
    },
  });
  if (model.isPending) return <Loading />;
  if (model.error) return <ErrorNotice error={model.error} />;
  const row = model.data!;
  return (
    <>
      <PageTitle
        eyebrow="REGISTRY / EXTERNAL MODEL FILE"
        title={row.filename}
        action={<Link to="/models">All models</Link>}
      >
        This file stays in its existing host location. AI Station stores
        metadata only and never downloads replacement weights.
      </PageTitle>
      <ErrorNotice
        error={
          save.error ??
          install.error ??
          load.error ??
          remove.error ??
          health.error ??
          restart.error ??
          null
        }
      />
      <section className="panel model-card">
        <h2>File observation</h2>
        <dl className="model-properties">
          <dt>Host path</dt>
          <dd className="model-path">
            {row.relative_path
              ? `Application data / ${row.relative_path}`
              : row.host_path}
          </dd>
          <dt>Configured root</dt>
          <dd className="model-path">{row.root_label}</dd>
          <dt>Format / size</dt>
          <dd>
            {row.format} · {size(row.size_bytes)}
          </dd>
          <dt>Observation</dt>
          <dd>{row.availability}</dd>
          <dt>Last seen</dt>
          <dd>
            {row.last_seen_at
              ? new Date(row.last_seen_at).toLocaleString()
              : "Unknown"}
          </dd>
          <dt>Family / quantization hints</dt>
          <dd>
            {row.family || "Unknown"} / {row.quantization || "Unknown"}
          </dd>
          <dt>Capability hints</dt>
          <dd>{row.capabilities.join(", ") || "Unknown"}</dd>
        </dl>
        <p className="muted">
          Family, quantization and capability hints are inferred from filenames
          and root names. They do not prove runtime compatibility or that a
          model is loaded.
        </p>
        {row.last_scan_run_id && (
          <Link to={`/runs/${row.last_scan_run_id}`}>
            Inspect discovery Run and report
          </Link>
        )}
      </section>
      <section className="panel model-card">
        <h2>
          {definition?.image_backend
            ? "Image model"
            : "Model definition and load preset"}
        </h2>
        {definition ? (
          <p>
            Status: <Badge status={definition.status} />
            {definition.last_verify_run_id && (
              <>
                {" "}
                <Link to={`/runs/${definition.last_verify_run_id}`}>
                  Latest install Run
                </Link>
              </>
            )}
          </p>
        ) : (
          <p className="muted">
            {canManage
              ? "Discovery does not create definitions. Save one explicitly, then install it to confirm the local file (and llama.cpp image, when applicable) without downloading anything."
              : row.category === "llm" && row.format === "gguf"
                ? "No saved preset. You can select this model in a conversation; AI Station prepares it when needed."
                : "No saved setup. An administrator can configure this model for its supported workspace."}
          </p>
        )}
        {definition?.compatibility && (
          <p>
            {definition.image_backend
              ? definition.compatibility.summary
              : definition.compatibility.operational
                ? "Declared adapter: managed llama.cpp. Registration is not a successful load."
                : definition.compatibility.summary}
          </p>
        )}
        <form
          className="model-definition-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (canManage) save.mutate();
          }}
        >
          {canManage ? (
            <>
              <label>
                Display name
                <input
                  value={selectedName}
                  onChange={(event) => setName(event.target.value)}
                  maxLength={200}
                  required
                />
              </label>
              {!definition?.image_backend && (
                <>
                  <label>
                    Context size
                    <input
                      type="number"
                      min={512}
                      max={262144}
                      step={256}
                      value={selectedContext}
                      onChange={(event) =>
                        setContext(Number(event.target.value))
                      }
                    />
                  </label>
                  <label>
                    KV cache
                    <select
                      value={selectedCache}
                      onChange={(event) =>
                        setCacheType(event.target.value as "f16" | "q8_0")
                      }
                    >
                      <option value="f16">f16</option>
                      <option value="q8_0">q8_0</option>
                    </select>
                  </label>
                  <fieldset>
                    <legend>Saved GPU preset</legend>
                    {(hardware.data?.gpus ?? []).length ? (
                      <GpuChoiceList
                        gpus={hardware.data?.gpus ?? []}
                        selected={selectedGpus}
                        onChange={setGpus}
                      />
                    ) : (
                      <p className="muted">
                        No GPUs reported. An empty preset loads on CPU after
                        installation.
                      </p>
                    )}
                  </fieldset>
                </>
              )}
            </>
          ) : definition ? (
            <dl className="model-properties">
              <dt>Name</dt>
              <dd>{definition.name}</dd>
              {!definition.image_backend && (
                <>
                  <dt>Saved context</dt>
                  <dd>
                    {definition.preset.context_size.toLocaleString()} tokens
                  </dd>
                  <dt>KV cache</dt>
                  <dd>{definition.preset.cache_type}</dd>
                  <dt>GPUs</dt>
                  <dd>
                    {definition.preset.gpus.length
                      ? definition.preset.gpus.join(", ")
                      : "CPU"}
                  </dd>
                </>
              )}
            </dl>
          ) : null}
          {definition?.image_backend && (
            <Link to={`/images?model=${definition.id}`}>
              Choose this model in Images
            </Link>
          )}
          <div className="row">
            {canManage && (
              <Button type="submit" disabled={save.isPending}>
                {definition?.image_backend
                  ? "Save name"
                  : definition
                    ? "Save preset"
                    : "Save definition"}
              </Button>
            )}
            {canManage && definition && (
              <Button
                type="button"
                variant="secondary"
                disabled={install.isPending}
                onClick={() => install.mutate(definition.id)}
              >
                {definition.status === "registered"
                  ? "Re-check installation"
                  : "Install locally"}
              </Button>
            )}
            {definition?.status === "registered" &&
              !definition.image_backend &&
              definition.compatibility?.operational && (
                <Button
                  type="button"
                  variant="secondary"
                  disabled={
                    load.isPending ||
                    Boolean(
                      instance &&
                      !["stopped", "failed"].includes(instance.status),
                    )
                  }
                  onClick={() => load.mutate(definition.id)}
                >
                  Load with saved preset
                </Button>
              )}
            {canManage && definition && (
              <Button
                type="button"
                variant="ghost"
                disabled={remove.isPending}
                onClick={() => remove.mutate(definition.id)}
              >
                Remove definition
              </Button>
            )}
          </div>
        </form>
        {canManage ? (
          <p className="muted">
            Install confirms the existing file and, for GGUF language models,
            that the configured llama.cpp image is already on this machine. It
            does not pull images or copy weights. Load starts the existing owned
            llama.cpp Run.
          </p>
        ) : (
          <p className="muted">
            Models are shared across accounts. An administrator manages their
            saved configuration.
          </p>
        )}
        {instance && (
          <div>
            <h3>Owned runtime</h3>
            <p>
              Status: <Badge status={instance.status} />
              {instance.metadata.health
                ? ` · last health ${instance.metadata.health.status}${
                    instance.metadata.health.n_ctx
                      ? ` · n_ctx ${instance.metadata.health.n_ctx}`
                      : ""
                  }`
                : " · no health check yet"}
            </p>
            <div className="row">
              <Button
                type="button"
                variant="secondary"
                disabled={health.isPending}
                onClick={() => health.mutate(instance.id)}
              >
                Check health
              </Button>
              {canManage &&
                (instance.status === "ready" ||
                  instance.status === "stopped" ||
                  instance.status === "failed") && (
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={restart.isPending}
                    onClick={() => restart.mutate(instance.id)}
                  >
                    Restart owned runtime
                  </Button>
                )}
              {instance.metadata.health_run_id && (
                <Link to={`/runs/${instance.metadata.health_run_id}`}>
                  Latest health Run
                </Link>
              )}
            </div>
            <p className="muted">
              Health inspects only this AI Station-owned llama.cpp container. It
              does not stop, restart or signal external processes such as
              Ollama.
            </p>
          </div>
        )}
        {canManage && <Link to="/system">Inspect runtime diagnostics</Link>}
      </section>
    </>
  );
}
