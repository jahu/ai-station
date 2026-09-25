import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Box, RefreshCw } from "lucide-react";
import { api, type Run } from "../api";
import {
  Badge,
  Empty,
  ErrorNotice,
  Loading,
  PageTitle,
} from "../components/common";
import { Button } from "../components/ui/button";

interface ModelFile {
  id: string;
  filename: string;
  host_path: string;
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
  definitions?: {
    id: string;
    name: string;
    category: string;
    capabilities: string[];
  }[];
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

export function Models() {
  const navigate = useNavigate();
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
          <Button
            onClick={() => scan.mutate()}
            disabled={scan.isPending || Boolean(active)}
          >
            <RefreshCw size={16} />
            {active ? "Scan in progress" : "Discover models"}
          </Button>
        }
      >
        Your existing model files, observed on the host. Discovery reads
        metadata and leaves files in place.
      </PageTitle>
      <ErrorNotice error={inventory.error ?? scan.error} />
      <section className="panel model-toolbar">
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
        {latest && (
          <div className="row">
            <Link to={`/runs/${latest.id}`}>Latest discovery Run</Link>
            <Badge status={latest.status} />
          </div>
        )}
      </section>
      {inventory.isPending ? (
        <Loading />
      ) : inventory.data?.items.length === 0 ? (
        <section className="panel">
          <Empty title="No model files in this view">
            Use Discover models to scan the Host Runner’s configured roots, or
            adjust the filter. No models are downloaded automatically.
          </Empty>
        </section>
      ) : (
        <div className="model-grid">
          {inventory.data?.items.map((model) => (
            <Link
              className="panel model-card"
              to={`/models/${model.id}`}
              key={model.id}
            >
              <div className="row">
                <Box size={20} />
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
              <p className="muted model-path">{model.host_path}</p>
              <small className="muted">
                {model.last_seen_at
                  ? `Last seen ${new Date(model.last_seen_at).toLocaleString()}`
                  : "No verified observation"}
              </small>
            </Link>
          ))}
        </div>
      )}
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
    </>
  );
}

export function ModelDetail() {
  const { id } = useParams();
  const model = useQuery({
    queryKey: ["model", id],
    queryFn: () => api<ModelFile>(`/models/${id}`),
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
        metadata only.
      </PageTitle>
      <section className="panel model-card">
        <h2>File observation</h2>
        <dl className="model-properties">
          <dt>Host path</dt>
          <dd className="model-path">{row.host_path}</dd>
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
        <h2>Model definitions</h2>
        {row.definitions?.length ? (
          row.definitions.map((d) => (
            <p key={d.id}>
              {d.name} · {d.category}
            </p>
          ))
        ) : (
          <p className="muted">
            No curated definition is linked to this file. A model file, its
            definition and a running runtime instance are separate records.
          </p>
        )}
        <Link to="/system">Inspect runtime diagnostics</Link>
      </section>
    </>
  );
}
