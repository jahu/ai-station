import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowLeft, ArrowRight, Search, ShieldCheck } from "lucide-react";
import { api, type Run } from "../api";
import { useAccount } from "../account-context";
import { ErrorNotice, PageTitle } from "../components/common";
import { Button } from "../components/ui/button";
import { randomId } from "../lib/random-id";
import HubInstallPanel from "./HubInstallPanel";
import "./ModelDiscover.css";

type Profile = {
  catalog_id: string;
  capability?: string;
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
    hardware_status: string;
    reason: string;
    profiles: Profile[];
    disk: {
      status: string;
      free_bytes: number | null;
      install_bytes_upper_bound?: number;
    };
    variant_advice?: {
      recommended: boolean;
      context_target: number | null;
      meets_context_target: boolean | null;
      precision_tradeoff: boolean;
      reason: string;
    };
  };
};
type Report = {
  kind?: "search" | "install_plan" | "comparison";
  observation_sha256?: string;
  manifest_sha256?: string;
  source_inspection_run_id?: string;
  source_inspection_repository?: string;
  search_run_id?: string;
  query?: string;
  repository?: string;
  revision?: string;
  license?: string;
  source_url?: string;
  license_url?: string;
  gated?: boolean;
  requirements_error?: string;
  context_target?: number;
  observed_at: string;
  items?: {
    repository: string;
    pipeline_hint: string;
    downloads: number | null;
    suitability?: string;
    summary?: string;
    filename?: string;
    busy_now?: boolean;
    installed_object?: boolean;
    observation?: Report;
  }[];
  candidate?: {
    capability: "chat" | "image" | "video" | "speech";
    setup_recipe?: {
      component_licenses: { name: string; url: string }[];
      inputs: {
        role?: string;
        kind?: string;
        filename: string;
        size_bytes: number;
      }[];
    };
    component_licenses?: { name: string; url: string }[];
    prepare_engine?: boolean;
  };
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
  const [contextChoice, setContextChoice] = useState<{
    runId: string;
    target: number;
  } | null>(null);
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
  const compare = useMutation({
    mutationFn: () =>
      api<Run>(
        "/model-hub/comparisons",
        post({
          client_request_id: randomId(),
          search_run_id: runId,
          observation_sha256: rootReport?.observation_sha256,
          context_target: contextTarget,
        }),
      ),
    onSuccess: (run) => setParams({ run: run.id }),
  });
  const plan = useMutation({
    mutationFn: ({
      filename,
      observation,
    }: {
      filename: string;
      observation: string;
    }) =>
      api<Run>(
        "/model-hub/plans",
        post({
          client_request_id: randomId(),
          inspection_run_id: runId,
          observation_sha256: observation,
          filename,
          context_target: contextTarget,
        }),
      ),
    onSuccess: (run) => setParams({ run: run.id }),
  });
  const run = inspection.data;
  const busy =
    find.isPending ||
    compare.isPending ||
    plan.isPending ||
    (!!runId && inspection.isPending) ||
    (!!run && !terminal.includes(run.status));
  const rootReport = run?.metadata?.source_inspection as Report | undefined;
  const contextTarget =
    contextChoice?.runId === runId
      ? contextChoice.target
      : (rootReport?.context_target ?? 32768);
  function setContextTarget(target: number) {
    setContextChoice({ runId, target });
  }
  const repository = params.get("repository");
  const report =
    (rootReport?.kind === "comparison" && repository
      ? rootReport.items?.find((item) => item.repository === repository)
          ?.observation
      : undefined) ?? rootReport;
  const trustedRun = run?.executor_type === "model_hub_inspect";
  const variants = report?.files ?? [];
  const preferred =
    variants.find((file) => file.assessment.variant_advice?.recommended) ??
    variants.find((file) =>
      file.assessment.profiles.some(
        (profile) => profile.fit === "estimated_fit",
      ),
    ) ??
    variants[0];
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
      <ErrorNotice
        error={
          find.error ??
          compare.error ??
          plan.error ??
          inspection.error ??
          stop.error
        }
      />
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
          {!!report.items?.length && (
            <>
              <details className="hub-context-options">
                <summary>Context options</summary>
                <label htmlFor="model-comparison-context">
                  Conversation context target
                </label>
                <select
                  id="model-comparison-context"
                  value={contextTarget}
                  onChange={(event) =>
                    setContextTarget(Number(event.target.value))
                  }
                >
                  <option value={32768}>32K · Balanced conversation</option>
                  <option value={131072}>128K · Longer tasks</option>
                </select>
                <p className="muted">
                  For conversation models. Media uses its supported workload
                  profile.
                </p>
              </details>
              <Button
                variant="secondary"
                disabled={!canManage || compare.isPending}
                onClick={() => compare.mutate()}
              >
                Compare top 3 for my hardware
              </Button>
            </>
          )}
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
      {!busy && trustedRun && report?.kind === "comparison" && (
        <section
          className="hub-results"
          aria-label="Hardware comparison results"
        >
          {report.search_run_id && (
            <Button
              variant="ghost"
              onClick={() => setParams({ run: report.search_run_id! })}
            >
              ← Back to search results
            </Button>
          )}
          <div className="hub-section-heading">
            <h2>Models for your station</h2>
            <span className="muted">Compared up to 3 matches</span>
          </div>
          <p className="muted">
            {report.query && <>For “{report.query}”. </>}
            Supported workload, fitted context and storage come before
            popularity. These are estimates, not quality or speed benchmarks. No
            weights were downloaded.
          </p>
          <p className="muted">
            Conversation target:{" "}
            {(report.context_target ?? 32768).toLocaleString()} tokens. Media
            models use their supported workload profile.
          </p>
          {report.items?.map((item) => (
            <article className="panel hub-repository" key={item.repository}>
              <div>
                <h3>{item.repository}</h3>
                <span className="badge">
                  {(
                    {
                      fits: "Estimated fit",
                      access_required: "Publisher access required",
                      limited_context: "Shorter context only",
                      unsupported: "Needs a compatible runtime",
                      unknown: "Requirements unknown",
                      insufficient_storage: "Not enough storage",
                      does_not_fit: "Does not fit",
                      unavailable: "Source unavailable",
                    } as Record<string, string>
                  )[item.suitability ?? ""] ?? "Needs review"}
                </span>
                <p>{item.summary}</p>
                {item.filename && (
                  <small className="muted model-path">{item.filename}</small>
                )}
                {item.busy_now && (
                  <p className="muted">
                    Fits with resources free; GPU memory is currently in use.
                  </p>
                )}
                {item.installed_object && (
                  <p className="muted">
                    Previously registered object · checked again during
                    installation.
                  </p>
                )}
              </div>
              {item.observation ? (
                <Button
                  variant="secondary"
                  onClick={() => {
                    setSelection({ runId: "", filename: "" });
                    setParams({ run: runId, repository: item.repository });
                  }}
                >
                  Review variants <ArrowRight size={15} />
                </Button>
              ) : (
                <Button
                  variant="secondary"
                  onClick={() => {
                    setQuery(item.repository);
                    find.mutate(item.repository);
                  }}
                >
                  Inspect separately <ArrowRight size={15} />
                </Button>
              )}
            </article>
          ))}
        </section>
      )}
      {rootReport?.kind === "comparison" && report !== rootReport && (
        <Button variant="ghost" onClick={() => setParams({ run: runId })}>
          ← Back to compared models
        </Button>
      )}
      {!busy && trustedRun && report?.repository && (
        <section className="hub-results" aria-label="Model source review">
          {report.kind === "install_plan" &&
            report.source_inspection_run_id && (
              <Button
                variant="ghost"
                onClick={() =>
                  setParams({
                    run: report.source_inspection_run_id!,
                    ...(report.source_inspection_repository
                      ? { repository: report.source_inspection_repository }
                      : {}),
                  })
                }
              >
                ← Back to variants
              </Button>
            )}
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
          {report.requirements_error && (
            <p className="notice">
              Hardware requirements could not be established:{" "}
              {report.requirements_error}
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
                    {file.assessment.variant_advice?.recommended
                      ? " · Recommended for this station"
                      : file.assessment.profiles.some(
                            (p) => p.fit === "estimated_fit",
                          )
                        ? " · Estimated fit"
                        : ""}
                  </option>
                ))}
              </select>
              <p className="muted">
                Recommendations balance context, GPU count and quantization
                within this model. They are estimates, not speed or quality
                benchmarks. You can choose another variant.
              </p>
            </div>
          )}
          {(selectedVariant ? [selectedVariant] : []).map((file) => (
            <article className="panel hub-variant" key={file.filename}>
              <div className="hub-section-heading">
                <h3>{file.filename}</h3>
                <span className="tiny-tag">
                  {file.assessment.variant_advice?.recommended
                    ? "Recommended · "
                    : ""}
                  {file.format} · {bytes(file.size_bytes)}
                </span>
              </div>
              <p>{file.assessment.reason}</p>
              {file.assessment.variant_advice &&
                !!file.assessment.profiles.length && (
                  <div className="hub-fit-summary">
                    <strong>{file.assessment.variant_advice.reason}</strong>
                    {file.assessment.variant_advice.context_target != null &&
                      !file.assessment.variant_advice.meets_context_target && (
                        <p>
                          This variant does not meet the{" "}
                          {file.assessment.variant_advice.context_target.toLocaleString()}
                          -token target on this station. Choose another model,
                          variant or a shorter target. The model’s trained limit
                          also applies.
                        </p>
                      )}
                    {file.assessment.variant_advice.precision_tradeoff && (
                      <p>
                        Low-bit quantization reduces memory use with a larger
                        precision tradeoff.
                      </p>
                    )}
                  </div>
                )}
              <p className="muted">
                {file.assessment.disk.install_bytes_upper_bound != null && (
                  <>
                    Additional installation reserve: up to{" "}
                    {bytes(file.assessment.disk.install_bytes_upper_bound)}{" "}
                    after verified cache reuse.{" "}
                  </>
                )}
                {file.assessment.disk.status === "insufficient"
                  ? "Not enough disk space, including safety headroom."
                  : file.assessment.disk.status === "unknown"
                    ? "Free application storage could not be confirmed."
                    : file.assessment.disk.install_bytes_upper_bound != null
                      ? "The reviewed installation reserve fits on disk, including the required engine and companions."
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
              {report.kind !== "install_plan" &&
                ["gguf", "safetensors"].includes(file.format) &&
                file.sha256 && (
                  <>
                    {!file.assessment.profiles.some(
                      (p) =>
                        p.capability === "image" ||
                        p.capability === "video" ||
                        p.capability === "speech",
                    ) && (
                      <details className="hub-context-options">
                        <summary>Context options</summary>
                        <label htmlFor="model-hub-context">
                          Context for installation
                        </label>
                        <select
                          id="model-hub-context"
                          value={contextTarget}
                          onChange={(event) =>
                            setContextTarget(Number(event.target.value))
                          }
                        >
                          <option value={32768}>
                            32K · Balanced conversation
                          </option>
                          <option value={131072}>128K · Longer tasks</option>
                        </select>
                        <p className="muted">
                          Variant recommendations use a 32K target. The
                          installation review checks your chosen target against
                          GPU memory and the model’s trained limit, and shows
                          the context that fits.
                        </p>
                      </details>
                    )}
                    <Button
                      variant="secondary"
                      disabled={
                        !canManage ||
                        !report.observation_sha256 ||
                        plan.isPending
                      }
                      onClick={() =>
                        plan.mutate({
                          filename: file.filename,
                          observation: report.observation_sha256!,
                        })
                      }
                    >
                      Review installation <ArrowRight size={16} />
                    </Button>
                  </>
                )}
              {!!file.assessment.profiles.length &&
                report.kind !== "install_plan" && (
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
          {report.kind === "install_plan" && report.manifest_sha256 && (
            <HubInstallPanel
              key={runId}
              runId={runId}
              plan={{
                manifest_sha256: report.manifest_sha256,
                capability: report.candidate?.capability,
                components: report.candidate?.prepare_engine
                  ? report.candidate.setup_recipe?.inputs
                      .filter(
                        (file) =>
                          !!file.role ||
                          file.kind === "model" ||
                          file.kind === "python" ||
                          file.kind === "sdk",
                      )
                      .map((file) => ({
                        ...file,
                        role: file.role ?? file.filename,
                      }))
                  : undefined,
                component_licenses:
                  report.candidate?.component_licenses ??
                  report.candidate?.setup_recipe?.component_licenses,
                license: report.license ?? "Not declared",
                license_url: report.license_url ?? report.source_url ?? "",
                files: report.files,
              }}
              canManage={canManage}
              downloadId={params.get("download") ?? ""}
              onDownload={(id) => setParams({ run: runId, download: id })}
            />
          )}
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
