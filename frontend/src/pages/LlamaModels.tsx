import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Check, ChevronDown, Cpu, Search, Server, X } from "lucide-react";
import { api, useHardware, type Run } from "../api";
import { ErrorNotice, Loading } from "../components/common";
import { Button } from "../components/ui/button";

type Model = {
  id: string;
  name: string;
  size_bytes: number;
  model_key: string;
};
type Instance = {
  id: string;
  name: string;
  status: string;
  metadata: {
    model_file_id: string;
    gpus: number[];
    context_size?: number;
    load_run_id: string;
    operation_run_id?: string;
    observation?: { error?: string };
  };
};
type Catalog = { models: Model[]; instances: Instance[] };
function modelName(name: string) {
  const parts = name.replace(/\.gguf$/i, "").split(" · ");
  if (
    parts.length === 2 &&
    parts[1].toLowerCase().startsWith(parts[0].toLowerCase())
  )
    return parts[1];
  return parts.join(" · ");
}
function stateLabel(instance?: Instance) {
  if (!instance || instance.status === "stopped") return "Loads when needed";
  return (
    {
      ready: "Ready",
      queued: "Queued",
      loading: "Loading",
      stopping: "Unloading",
      failed: "Retry available",
      unknown: "Needs inspection",
    }[instance.status] ?? instance.status
  );
}

export default function LlamaModels({
  value,
  label,
  models,
  onSelect,
  busy,
  onBusy,
  compact = false,
  coding = false,
}: {
  value: string;
  label?: string;
  models: string[];
  onSelect: (model: string) => void;
  busy: boolean;
  onBusy?: (busy: boolean) => void;
  compact?: boolean;
  coding?: boolean;
}) {
  const cache = useQueryClient();
  const hardware = useHardware();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(value);
  const [search, setSearch] = useState("");
  const [gpus, setGpus] = useState<number[] | null>(null);
  const [context, setContext] = useState(coding ? 131072 : 4096);
  const [runId, setRunId] = useState<string | null>(null);
  const catalog = useQuery({
    queryKey: ["llama-models"],
    queryFn: () => api<Catalog>("/llama"),
    refetchInterval: open ? 2000 : false,
  });
  const selectedGpus =
    gpus ?? (hardware.data?.gpus ?? []).map((g) => Number(g.index));
  function instanceFor(model?: Model) {
    const matching =
      catalog.data?.instances.filter(
        (i) => i.metadata.model_file_id === model?.id,
      ) ?? [];
    return (
      matching.find((i) => !["stopped", "failed"].includes(i.status)) ??
      matching.at(-1)
    );
  }
  const choice = catalog.data?.models.find((m) => m.model_key === draft);
  const instance = instanceFor(choice);
  const current = catalog.data?.models.find((m) => m.model_key === value);
  const localModels = [
    ...new Set(models.filter((m) => !m.startsWith("llamacpp:"))),
  ];
  if (value && !value.startsWith("llamacpp:") && !localModels.includes(value))
    localModels.push(value);
  const load = useMutation({
    mutationFn: (model: Model) =>
      api<Run>("/llama/load", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model_file_id: model.id,
          gpus: selectedGpus,
          context_size: context,
          ...(coding ? { cache_type: "q8_0" } : {}),
        }),
      }),
    onMutate: () => onBusy?.(true),
    onSuccess: (run, model) => {
      setRunId(run.id);
      onSelect(model.model_key);
      setOpen(false);
      void cache.invalidateQueries({ queryKey: ["llama-models"] });
    },
    onSettled: () => onBusy?.(false),
  });
  const stop = useMutation({
    mutationFn: (id: string) =>
      api<Run>(`/llama/${id}/stop`, { method: "POST" }),
    onSuccess: (run) => {
      setRunId(run.id);
      void cache.invalidateQueries({ queryKey: ["llama-models"] });
    },
  });
  const pending = busy || load.isPending || stop.isPending;
  const needsSetup = !!choice && !instance;
  const invalid =
    !draft.trim() ||
    draft.length > 200 ||
    (draft.startsWith("llamacpp:") &&
      (!choice || instance?.status === "unknown")) ||
    (needsSetup &&
      (hardware.isPending ||
        !!hardware.error ||
        !Number.isInteger(context) ||
        context < 512 ||
        context > 262144 ||
        context % 256 !== 0));
  const matches = (name: string) =>
    name.toLowerCase().includes(search.toLowerCase());
  const available = catalog.data?.models.filter((m) => matches(m.name)) ?? [];
  const providers = localModels.filter(matches);
  function choose() {
    if (pending || invalid) return;
    if (needsSetup) load.mutate(choice);
    else {
      onSelect(draft.trim());
      setOpen(false);
    }
  }
  return (
    <div className={`model-picker ${compact ? "model-picker-compact" : ""}`}>
      <Dialog.Root
        open={open}
        onOpenChange={(next) => {
          if (load.isPending) return;
          if (next) {
            setDraft(value);
            setSearch("");
            load.reset();
            stop.reset();
          }
          setOpen(next);
        }}
      >
        <Dialog.Trigger asChild>
          <button
            type="button"
            className="model-picker-trigger"
            disabled={pending}
            aria-label={compact ? "Change model" : "Model"}
          >
            <Cpu size={18} />
            <span>
              <strong>
                {modelName(
                  current?.name ||
                    label ||
                    (value.startsWith("llamacpp:")
                      ? "Local GGUF model"
                      : value),
                ) || "Choose a model"}
              </strong>
              <small>
                {value.startsWith("llamacpp:")
                  ? "llama.cpp · local GGUF"
                  : "Local server · Ollama / compatible"}
              </small>
            </span>
            <ChevronDown size={16} />
          </button>
        </Dialog.Trigger>
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content className="model-dialog">
            <div className="model-dialog-heading">
              <div>
                <Dialog.Title>Choose a model</Dialog.Title>
                <Dialog.Description>
                  Run a model from your disk with llama.cpp, or use your
                  configured local server.
                </Dialog.Description>
              </div>
              <Dialog.Close
                className="icon-button"
                aria-label="Close model picker"
              >
                <X size={20} />
              </Dialog.Close>
            </div>
            <label className="model-search">
              <Search size={17} />
              <input
                aria-label="Search models"
                placeholder="Find a model, size or quantization…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </label>
            <ErrorNotice
              error={
                catalog.error ??
                load.error ??
                stop.error ??
                (needsSetup ? hardware.error : null)
              }
            />
            <div
              className="model-options"
              role="group"
              aria-label="Available models"
            >
              <div className="model-group-label">
                <Cpu size={13} /> llama.cpp <span>FROM YOUR DISK</span>
              </div>
              {catalog.isPending && <Loading />}
              {available.map((model) => {
                const runtime = instanceFor(model);
                return (
                  <button
                    type="button"
                    key={model.id}
                    className="model-option"
                    aria-label={`${modelName(model.name)}, llama.cpp, ${stateLabel(runtime)}`}
                    aria-pressed={draft === model.model_key}
                    disabled={pending}
                    onClick={() => setDraft(model.model_key)}
                  >
                    <span className="model-option-icon">
                      <Cpu size={20} />
                    </span>
                    <span className="model-option-content">
                      <strong>{modelName(model.name)}</strong>
                      <small>
                        {(model.size_bytes / 1024 ** 3).toFixed(1)} GiB{" "}
                        <span>·</span> {stateLabel(runtime)}
                      </small>
                    </span>
                    <span className="model-option-check">
                      {draft === model.model_key && <Check size={18} />}
                    </span>
                  </button>
                );
              })}
              {!catalog.isPending && !available.length && (
                <p className="model-empty">
                  {search ? (
                    "No matching GGUF models."
                  ) : (
                    <>
                      No language models discovered yet.{" "}
                      <Link to="/models" onClick={() => setOpen(false)}>
                        Scan model folders →
                      </Link>
                    </>
                  )}
                </p>
              )}
              <div className="model-group-label">
                <Server size={13} /> Local server{" "}
                <span>OLLAMA / COMPATIBLE</span>
              </div>
              {providers.map((model) => (
                <button
                  type="button"
                  key={model}
                  className="model-option"
                  aria-label={`${model}, local server`}
                  aria-pressed={draft === model}
                  disabled={pending}
                  onClick={() => setDraft(model)}
                >
                  <span className="model-option-icon">
                    <Server size={20} />
                  </span>
                  <span className="model-option-content">
                    <strong>{model}</strong>
                    <small>Uses the configured endpoint</small>
                  </span>
                  <span className="model-option-check">
                    {draft === model && <Check size={18} />}
                  </span>
                </button>
              ))}
              {!providers.length && (
                <p className="model-empty">No matching server models.</p>
              )}
            </div>
            <details className="model-advanced">
              <summary>GPU, context and advanced options</summary>
              {choice ? (
                <>
                  <p>
                    {instance
                      ? "This model keeps its saved GPU and context settings when reloaded."
                      : "The first load uses these GPUs. Selecting several cards splits model layers across them; no cards uses the CPU."}
                  </p>
                  <fieldset
                    disabled={
                      pending ||
                      !!instance ||
                      hardware.isPending ||
                      !!hardware.error
                    }
                  >
                    <legend>GPU allocation</legend>
                    <div className="model-gpus">
                      {hardware.data?.gpus.map((gpu) => (
                        <label key={gpu.index}>
                          <input
                            type="checkbox"
                            checked={(
                              instance?.metadata.gpus ?? selectedGpus
                            ).includes(Number(gpu.index))}
                            onChange={(e) =>
                              setGpus(
                                e.target.checked
                                  ? [...selectedGpus, Number(gpu.index)]
                                  : selectedGpus.filter(
                                      (g) => g !== Number(gpu.index),
                                    ),
                              )
                            }
                          />
                          GPU {gpu.index} · {gpu.name}
                        </label>
                      ))}
                    </div>
                    {!selectedGpus.length && !instance && (
                      <p>CPU execution selected.</p>
                    )}
                    <label>
                      Context size
                      <input
                        type="number"
                        min={512}
                        max={262144}
                        step={256}
                        value={instance?.metadata.context_size ?? context}
                        onChange={(e) => setContext(Number(e.target.value))}
                      />
                    </label>
                  </fieldset>
                  {instance?.status === "ready" && (
                    <Button
                      type="button"
                      variant="secondary"
                      disabled={pending}
                      onClick={() => stop.mutate(instance.id)}
                    >
                      Unload model · release GPUs
                    </Button>
                  )}
                  {instance && (
                    <Link
                      to={`/runs/${instance.metadata.operation_run_id ?? instance.metadata.load_run_id}`}
                      onClick={() => setOpen(false)}
                    >
                      Inspect runtime / cancel
                    </Link>
                  )}
                  {instance?.metadata.observation?.error && (
                    <p className="notice">
                      {instance.metadata.observation.error}
                    </p>
                  )}
                </>
              ) : (
                <label>
                  Other model on configured server
                  <input
                    maxLength={200}
                    value={draft}
                    placeholder="Model name supplied by your server"
                    onChange={(e) => setDraft(e.target.value)}
                  />
                </label>
              )}
            </details>
            <div className="model-dialog-footer">
              <p>
                {needsSetup
                  ? "The first load starts when you select this model. Messages wait until it is ready."
                  : choice
                    ? "Loads automatically when your next message needs it."
                    : "Inference stays on your configured local server."}
              </p>
              <Button
                type="button"
                disabled={pending || invalid}
                onClick={choose}
              >
                {load.isPending ? "Preparing model…" : "Use model"}
              </Button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
      {runId && (
        <Link className="model-operation-link" to={`/runs/${runId}`}>
          Model operation →
        </Link>
      )}
    </div>
  );
}
