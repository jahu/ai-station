import { useRef, useState, useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, useHardware, type Run } from "../api";
import { ErrorNotice } from "../components/common";
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
    load_run_id: string;
    operation_run_id?: string;
    observation?: { error?: string };
  };
};
type Catalog = { models: Model[]; instances: Instance[] };

export default function LlamaModels({
  onSelect,
  busy,
}: {
  onSelect: (model: string) => void;
  busy: boolean;
}) {
  const cache = useQueryClient();
  const hardware = useHardware();
  const catalog = useQuery({
    queryKey: ["llama-models"],
    queryFn: () => api<Catalog>("/llama"),
    refetchInterval: 2000,
  });
  const [gpus, setGpus] = useState<number[] | null>(null);
  const [context, setContext] = useState(4096);
  const selected =
    gpus ?? (hardware.data?.gpus ?? []).map((g) => Number(g.index));
  const pendingSelection = useRef<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const load = useMutation({
    mutationFn: (model: Model) =>
      api<Run>("/llama/load", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model_file_id: model.id,
          gpus: selected,
          context_size: context,
        }),
      }),
    onSuccess: (run, model) => {
      pendingSelection.current = model.id;
      setRunId(run.id);
      void cache.invalidateQueries({ queryKey: ["llama-models"] });
    },
  });
  const stop = useMutation({
    mutationFn: (id: string) =>
      api<Run>(`/llama/${id}/stop`, { method: "POST" }),
    onSuccess: (run) => {
      setRunId(run.id);
      void cache.invalidateQueries({ queryKey: ["llama-models"] });
    },
  });
  useEffect(() => {
    const model = catalog.data?.models.find(
      (m) => m.id === pendingSelection.current,
    );
    if (
      model &&
      catalog.data?.instances.some(
        (i) => i.metadata.model_file_id === model.id && i.status === "ready",
      )
    ) {
      pendingSelection.current = null;
      onSelect(model.model_key);
    }
  }, [catalog.data, onSelect]);
  return (
    <details className="content-panel">
      <summary>Local model files · llama.cpp</summary>
      <p className="muted">
        Load a GGUF from your model registry. Selected GPUs share the model;
        they stay reserved until you stop it. Ollama and other configured
        providers remain available.
      </p>
      <ErrorNotice
        error={catalog.error ?? hardware.error ?? load.error ?? stop.error}
      />
      <fieldset disabled={busy || load.isPending || stop.isPending}>
        <legend>GPU allocation</legend>
        {hardware.data?.gpus.map((gpu) => (
          <label key={gpu.index}>
            <input
              type="checkbox"
              checked={selected.includes(Number(gpu.index))}
              onChange={(e) =>
                setGpus(
                  e.target.checked
                    ? [...selected, Number(gpu.index)]
                    : selected.filter((g) => g !== Number(gpu.index)),
                )
              }
            />
            GPU {gpu.index} · {gpu.name}
          </label>
        ))}
        {!selected.length && <p className="muted">CPU execution selected.</p>}
        <label>
          Runtime context size
          <input
            type="number"
            min={512}
            max={32768}
            step={256}
            value={context}
            onChange={(e) => setContext(Number(e.target.value))}
          />
        </label>
        {catalog.data?.models.map((model) => {
          const instance = catalog.data?.instances.find(
            (i) =>
              i.metadata.model_file_id === model.id &&
              !["stopped", "failed"].includes(i.status),
          );
          const latest =
            instance ??
            catalog.data?.instances
              .filter((i) => i.metadata.model_file_id === model.id)
              .at(-1);
          return (
            <div className="panel content-panel" key={model.id}>
              <strong>{model.name}</strong>
              <p className="muted">
                {(model.size_bytes / 1024 ** 3).toFixed(1)} GiB ·{" "}
                {instance?.status ?? "Stored on disk"}
              </p>
              {instance?.status === "ready" ? (
                <div className="row">
                  <Button
                    type="button"
                    onClick={() => onSelect(model.model_key)}
                  >
                    Use in this conversation
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => stop.mutate(instance.id)}
                  >
                    Stop model
                  </Button>
                </div>
              ) : instance ? (
                <Link
                  to={`/runs/${instance.metadata.operation_run_id ?? instance.metadata.load_run_id}`}
                >
                  Inspect runtime Run / cancel
                </Link>
              ) : (
                <Button type="button" onClick={() => load.mutate(model)}>
                  Load and select
                </Button>
              )}
              {latest?.metadata.observation?.error && (
                <p className="notice">{latest.metadata.observation.error}</p>
              )}
            </div>
          );
        })}
        {catalog.data && !catalog.data.models.length && (
          <p>
            No GGUFs have been discovered yet.{" "}
            <Link to="/models">Scan model roots in Models.</Link>
          </p>
        )}
      </fieldset>
      {runId && (
        <p>
          <Link to={`/runs/${runId}`}>Inspect runtime operation</Link>
        </p>
      )}
    </details>
  );
}
