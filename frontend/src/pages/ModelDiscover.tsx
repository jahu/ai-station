import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowLeft, ArrowRight, Search, ShieldCheck } from "lucide-react";
import { api, type Run } from "../api";
import { useAccount } from "../account-context";
import { ErrorNotice, PageTitle } from "../components/common";
import { Button } from "../components/ui/button";
import { randomId } from "../lib/random-id";
import "./ModelDiscover.css";

type Profile = {
  catalog_id: string;
  name: string;
  fit: string;
  occupancy: string;
  recommendation: {
    reason: string;
    gpus: number[];
    context_size: number | null;
    runtime_profile?: string;
  };
};
type ModelFile = {
  filename: string;
  size_bytes: number | null;
  sha256: string | null;
  format: string;
  unsafe_serialization: boolean;
  assessment: {
    reason: string;
    profiles: Profile[];
    disk: { status: string; free_bytes: number | null };
  };
};
type Report = {
  kind?: "search";
  query?: string;
  repository?: string;
  revision?: string;
  license?: string;
  source_url?: string;
  license_url?: string;
  gated?: boolean;
  observed_at: string;
  items?: {
    repository: string;
    pipeline_hint: string;
    downloads: number | null;
  }[];
  files: ModelFile[];
};
const terminal = ["succeeded", "failed", "canceled", "interrupted"];
const bytes = (value: number | null) =>
  value === null ? "Size unknown" : `${(value / 1024 ** 3).toFixed(2)} GiB`;
const post = (body: unknown) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
const isSource = (value: string) =>
  /^https?:\/\//i.test(value) ||
  /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(value);

export default function ModelDiscover() {
  const account = useAccount();
  const canManage =
    account.mode === "operator" || account.user?.is_admin === true;
  const [query, setQuery] = useState("");
  const [selection, setSelection] = useState({ runId: "", filename: "" });
  const [params, setParams] = useSearchParams();
  const runId = params.get("run") || "";
  const inspection = useQuery({
    queryKey: ["model-hub", runId],
    queryFn: async ({ signal }) => {
      const run = await api<Run>(`/runs/${runId}`, { signal });
      if (run.executor_type !== "model_hub_inspect")
        throw new Error("This link is not a model-source inspection.");
      return run;
    },
    enabled: !!runId,
    refetchInterval: (q) =>
      q.state.data && terminal.includes(q.state.data.status) ? false : 1500,
  });
  const find = useMutation({
    mutationFn: (value: string) => {
      const source = isSource(value);
      return api<Run>(
        `/model-hub/${source ? "inspections" : "searches"}`,
        post({
          client_request_id: randomId(),
          [source ? "source" : "query"]: value,
        }),
      );
    },
    onSuccess: (run) => setParams({ run: run.id }),
  });
  const stop = useMutation({
    mutationFn: () => api<Run>(`/runs/${runId}/cancel`, post({})),
    onSuccess: () => void inspection.refetch(),
  });
  const run = inspection.data;
  const busy = find.isPending || (!!run && !terminal.includes(run.status));
  const report = run?.metadata?.source_inspection as Report | undefined;
  const trustedRun = run?.executor_type === "model_hub_inspect";
  const variants = report?.files ?? [];
  const preferred =
    variants.find((file) =>
      file.assessment.profiles.some(
        (profile) => profile.fit === "estimated_fit",
      ),
    ) ?? variants[0];
  const selectedVariant =
    (selection.runId === runId
      ? variants.find((file) => file.filename === selection.filename)
      : undefined) ?? preferred;
  return (
    <div className="model-discover">
      <Link className="text-link" to="/models">
        <ArrowLeft size={14} /> Installed models
      </Link>
      <PageTitle eyebrow="MODELS / DISCOVER" title="Find your next model">
        Search Hugging Face or paste a repository or file link. Review the
        source, supported runtime and fit for your station before downloading.
      </PageTitle>
      <form
        className="panel hub-search"
        onSubmit={(event) => {
          event.preventDefault();
          if (query.trim().length >= 2 && !busy) find.mutate(query.trim());
        }}
      >
        <label htmlFor="model-hub-query">Model name or Hugging Face link</label>
        <div className="hub-search-row">
          <Search size={20} aria-hidden="true" />
          <input
            id="model-hub-query"
            value={query}
            maxLength={1800}
            placeholder="Search models, or paste https://huggingface.co/…"
            onChange={(event) => setQuery(event.target.value)}
            disabled={!canManage}
          />
          <Button
            type="submit"
            disabled={!canManage || busy || query.trim().length < 2}
          >
            {find.isPending
              ? "Starting…"
              : isSource(query.trim())
                ? "Check model"
                : "Search"}
            <ArrowRight size={16} />
          </Button>
        </div>
        <p className="muted">
          Only public metadata is read. No weights are downloaded or models
          loaded.
        </p>
        {!canManage && (
          <p className="muted">
            An administrator manages shared model discovery and installation.
          </p>
        )}
      </form>
      <ErrorNotice error={find.error ?? inspection.error ?? stop.error} />
      {run && trustedRun && !find.isPending && (
        <div className="hub-inspection-status" role="status">
          <span>
            {busy
              ? "Reading publisher metadata and checking your station…"
              : run.status === "succeeded"
                ? "Source reviewed"
                : run.status === "failed"
                  ? run.error_message
                  : `Inspection ${run.status}`}
          </span>
          <Link className="text-link" to={`/runs/${run.id}`}>
            Inspection history ↗
          </Link>
          {busy && (
            <Button
              variant="ghost"
              onClick={() => stop.mutate()}
              disabled={stop.isPending}
            >
              Stop
            </Button>
          )}
        </div>
      )}
      {!busy && trustedRun && report?.kind === "search" && (
        <section className="hub-results" aria-label="Model search results">
          <div className="hub-section-heading">
            <h2>Matches for “{report.query}”</h2>
            <span className="muted">Up to 12 publisher matches</span>
          </div>
          <p className="muted">
            Ordered by downloads. Popularity does not establish compatibility or
            hardware fit.
          </p>
          {report.items?.map((item) => (
            <article className="panel hub-repository" key={item.repository}>
              <div>
                <h3>{item.repository}</h3>
                <p className="muted">
                  {item.pipeline_hint || "Capability not declared"}
                </p>
              </div>
              <Button
                variant="secondary"
                onClick={() => {
                  setQuery(item.repository);
                  find.mutate(item.repository);
                }}
              >
                Check fit <ArrowRight size={15} />
              </Button>
            </article>
          ))}
          {!report.items?.length && (
            <p>
              No public matches. Try a publisher name or paste a direct model
              link.
            </p>
          )}
        </section>
      )}
      {!busy && trustedRun && report?.repository && (
        <section className="hub-results" aria-label="Model source review">
          <div className="hub-section-heading">
            <h2>{report.repository}</h2>
            <span className="tiny-tag">Metadata reviewed</span>
          </div>
          <div className="hub-source-links">
            <a href={report.source_url} target="_blank" rel="noreferrer">
              Publisher ↗
            </a>
            <a href={report.license_url} target="_blank" rel="noreferrer">
              License: {report.license} ↗
            </a>
          </div>
          <p className="muted">
            Revision {report.revision?.slice(0, 12)} ·{" "}
            {new Date(report.observed_at).toLocaleString()}
          </p>
          {report.gated && (
            <p className="notice">
              Publisher access approval may be required. No account credentials
              were sent.
            </p>
          )}
          {variants.length > 1 && (
            <div className="hub-variant-choice">
              <label htmlFor="model-hub-variant">Choose a variant</label>
              <select
                id="model-hub-variant"
                value={selectedVariant?.filename ?? ""}
                onChange={(event) =>
                  setSelection({ runId, filename: event.target.value })
                }
              >
                {variants.map((file) => (
                  <option key={file.filename} value={file.filename}>
                    {file.filename} · {bytes(file.size_bytes)}
                    {file.assessment.profiles.some(
                      (p) => p.fit === "estimated_fit",
                    )
                      ? " · Estimated fit"
                      : ""}
                  </option>
                ))}
              </select>
              <p className="muted">
                A matching reviewed profile is selected first when available.
                Compare size and hardware requirements before choosing.
              </p>
            </div>
          )}
          {(selectedVariant ? [selectedVariant] : []).map((file) => (
            <article className="panel hub-variant" key={file.filename}>
              <div className="hub-section-heading">
                <h3>{file.filename}</h3>
                <span className="tiny-tag">
                  {file.format} · {bytes(file.size_bytes)}
                </span>
              </div>
              <p>{file.assessment.reason}</p>
              <p className="muted">
                {file.assessment.disk.status === "insufficient"
                  ? "Not enough disk space, including safety headroom."
                  : file.assessment.disk.status === "unknown"
                    ? "Free application storage could not be confirmed."
                    : "The file fits on disk; runtime and companions may require more space."}
              </p>
              {file.unsafe_serialization && (
                <p className="muted">
                  Executable weight serialization is not admitted from
                  unreviewed repositories.
                </p>
              )}
              {file.assessment.profiles.map((profile) => (
                <div className="hub-profile" key={profile.catalog_id}>
                  <ShieldCheck size={18} aria-hidden="true" />
                  <div>
                    <strong>{profile.name}</strong>
                    <p>{profile.recommendation.reason}</p>
                    {profile.recommendation.context_size && (
                      <p className="muted">
                        {profile.recommendation.gpus.length
                          ? `GPU ${profile.recommendation.gpus.join(" + ")}`
                          : "Explicit CPU profile"}{" "}
                        · {profile.recommendation.context_size.toLocaleString()}{" "}
                        context · estimate, not a local qualification
                      </p>
                    )}
                    {profile.occupancy === "in_use" && (
                      <p className="muted">
                        GPU memory is currently in use; capacity is estimated
                        with those resources free.
                      </p>
                    )}
                  </div>
                </div>
              ))}
              {!!file.assessment.profiles.length && (
                <Link className="text-link" to="/setup/models">
                  Review matching guided setup options →
                </Link>
              )}
              <details>
                <summary>File identity</summary>
                <p className="model-path">
                  SHA256:{" "}
                  {file.sha256 ||
                    "Publisher did not provide a verifiable SHA256"}
                </p>
              </details>
            </article>
          ))}
          {!report.files.length && (
            <p>
              No inspectable weight files in this selection. Choose a model
              repository or weight file.
            </p>
          )}
        </section>
      )}
      {!runId && (
        <div className="hub-intro panel">
          <ShieldCheck size={24} />
          <h2>A model that suits your station</h2>
          <p>
            Compatibility, memory and disk space are separate checks. A GGUF
            file can be a language model, image model or companion — its name
            alone is not enough.
          </p>
          <Link className="text-link" to="/setup/models">
            Start with a reviewed setup recommendation →
          </Link>
        </div>
      )}
    </div>
  );
}
