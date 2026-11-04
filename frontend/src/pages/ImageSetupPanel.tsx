import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowRight,
  Check,
  Download,
  ImagePlus,
  RotateCcw,
  Square,
} from "lucide-react";
import { api, type Run } from "../api";
import { Badge, ErrorNotice, Loading } from "../components/common";
import { Button } from "../components/ui/button";
import { randomId } from "../lib/random-id";

const profile = "qwen-image21-cuda-linux-amd64-v1";
const terminal = new Set(["succeeded", "failed", "canceled", "interrupted"]);
const size = (bytes: number) => `${(bytes / 1024 ** 3).toFixed(2)} GiB`;
const post = (body: unknown) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
type Catalog = {
  can_prepare: boolean;
  installation_available: boolean;
  installation_notice?: string;
  manifest_sha256: string;
  recipe?: {
    name: string;
    inputs: {
      filename: string;
      role: string;
      size_bytes: number;
      url: string;
      sha256: string;
    }[];
  };
  hardware?: {
    gpus: { index: number; name?: string; memory_total_mib?: number }[];
  };
  existing_images?: { available: boolean; source: string };
  storage?: {
    free_bytes: number;
    required_bytes: number;
    download_bytes: number;
    cached_model_bytes_estimate: number;
    docker_free_bytes: number | null;
    docker_required_bytes: number;
  };
  licenses?: { name: string; url: string }[];
};
type Preparation = {
  id: string;
  manifest_sha256: string;
  attempt: number;
  run: Run;
  resume_allowed: boolean;
  progress: {
    phase?: string;
    received_bytes?: number;
    expected_bytes?: number;
    current_file?: string;
  };
};
const phases: Record<string, string> = {
  downloading_files: "Downloading image models",
  verifying_files: "Verifying cached models",
  files_verified: "Models checked · preparing the image engine",
  runtime_pulling: "Downloading the image engine",
  runtime_downloading: "Downloading the image engine",
  runtime_verifying: "Checking the image engine",
  image_environment_prepared: "Installation prepared",
};

function ImagePreparation({
  value,
  canPrepare,
  available,
  ready,
  manifest,
  refresh,
}: {
  value: Preparation;
  canPrepare: boolean;
  available: boolean;
  ready: boolean;
  manifest?: string;
  refresh: () => void;
}) {
  const request = useRef<{ run: string; id: string } | null>(null);
  const active = !terminal.has(value.run.status);
  const action = useMutation({
    mutationFn: (kind: "cancel" | "resume") => {
      if (!request.current || request.current.run !== value.run.id)
        request.current = { run: value.run.id, id: randomId() };
      return api(
        `/setup/runtimes/preparations/${value.id}/${kind}`,
        post(
          kind === "resume"
            ? {
                client_request_id: request.current.id,
                expected_run_id: value.run.id,
              }
            : {},
        ),
      );
    },
    onSuccess: refresh,
  });
  const phase = value.progress.phase ?? "";
  const total = value.progress.expected_bytes ?? 0;
  const received = Math.max(
    0,
    Math.min(total, value.progress.received_bytes ?? 0),
  );
  const measured =
    total > 0 &&
    [
      "downloading_files",
      "verifying_files",
      "runtime_pulling",
      "runtime_downloading",
    ].includes(phase);
  const label =
    value.run.status === "queued"
      ? "Waiting for available resources"
      : value.run.status === "cancel_requested"
        ? "Stopping safely…"
        : value.run.status === "canceled"
          ? "Stopped · downloaded files are kept"
          : value.run.status === "succeeded"
            ? "Installation prepared"
            : active
              ? (phases[phase] ?? "Preparing the image engine")
              : "Preparation needs attention";
  return (
    <article
      className="setup-runtime-attempt"
      aria-label={`Image preparation ${value.id.slice(0, 8)}`}
    >
      <div className="row spread">
        <strong>{label}</strong>
        <Badge status={value.run.status} />
      </div>
      {active && (
        <>
          {measured ? (
            <progress
              aria-label="Image setup download progress"
              value={received}
              max={total}
            />
          ) : (
            <progress aria-label="Image engine preparation" />
          )}
          <p className="muted setup-small" role="status">
            {measured
              ? `${size(received)} of ${size(total)}${value.progress.current_file ? ` · ${value.progress.current_file}` : ""}`
              : "You can leave this page. Preparation keeps running and its progress is saved."}
          </p>
        </>
      )}
      {!active && value.run.error_message && (
        <p className="notice">{value.run.error_message}</p>
      )}
      <ErrorNotice error={action.error} />
      <div className="row speech-setup-actions">
        {canPrepare && active && (
          <Button
            variant="secondary"
            disabled={
              action.isPending || value.run.status === "cancel_requested"
            }
            onClick={() => action.mutate("cancel")}
          >
            <Square size={14} /> Stop image setup
          </Button>
        )}
        {canPrepare && value.resume_allowed && (
          <Button
            variant="secondary"
            disabled={
              action.isPending ||
              !available ||
              value.manifest_sha256 !== manifest
            }
            onClick={() => action.mutate("resume")}
          >
            <RotateCcw size={15} /> Resume image setup
          </Button>
        )}
        {value.run.status === "succeeded" && ready && (
          <Button asChild variant="secondary">
            <Link to="/images">
              <ImagePlus size={16} /> Create an image
            </Link>
          </Button>
        )}
        <Link className="text-link" to={`/runs/${value.run.id}`}>
          View details
        </Link>
        <small className="muted">
          Attempt {value.attempt} ·{" "}
          {new Date(value.run.created_at).toLocaleString()}
        </small>
      </div>
      {!active &&
        value.resume_allowed &&
        value.manifest_sha256 !== manifest && (
          <p className="muted setup-small">
            This attempt used an earlier model bundle. Review the current
            sources to start a new installation.
          </p>
        )}
    </article>
  );
}

export default function ImageSetupPanel() {
  const [search] = useSearchParams();
  const [opened, setOpened] = useState(false);
  const expanded = opened || search.get("capability") === "images";
  const section = useRef<HTMLElement>(null);
  const cache = useQueryClient();
  const catalog = useQuery({
    queryKey: ["image-setup-catalog"],
    queryFn: () => api<Catalog>(`/setup/runtimes?profile=${profile}`),
    enabled: expanded,
  });
  const history = useQuery({
    queryKey: ["image-preparations"],
    queryFn: () =>
      api<Preparation[]>(`/setup/runtimes/preparations?profile=${profile}`),
    enabled: expanded,
    refetchInterval: (query) =>
      query.state.data?.some((row) => !terminal.has(row.run.status))
        ? 1000
        : false,
  });
  const data = catalog.data;
  const [accepted, setAccepted] = useState("");
  const [showManaged, setShowManaged] = useState(false);
  const token = useRef<{ hash: string; id: string } | null>(null);
  const completed = useRef(new Set<string>());
  function refresh() {
    for (const key of [
      "image-preparations",
      "image-setup-catalog",
      "image-capabilities",
      "image-models",
      "models",
    ])
      void cache.invalidateQueries({ queryKey: [key] });
  }
  useEffect(() => {
    if (expanded && search.get("capability") === "images")
      section.current?.scrollIntoView?.({ block: "start", behavior: "smooth" });
  }, [expanded, search]);
  useEffect(() => {
    for (const row of history.data ?? [])
      if (
        row.run.status === "succeeded" &&
        !completed.current.has(row.run.id)
      ) {
        completed.current.add(row.run.id);
        for (const key of [
          "image-setup-catalog",
          "image-capabilities",
          "image-models",
          "models",
        ])
          void cache.invalidateQueries({ queryKey: [key] });
      }
  }, [history.data, cache]);
  const prepare = useMutation({
    mutationFn: () => {
      if (
        !data?.recipe ||
        !data.installation_available ||
        !data.can_prepare ||
        accepted !== data.manifest_sha256
      )
        throw new Error(
          "Review the image models and component licenses before installation.",
        );
      if (!token.current || token.current.hash !== data.manifest_sha256)
        token.current = { hash: data.manifest_sha256, id: randomId() };
      return api(
        "/setup/runtimes",
        post({
          client_request_id: token.current.id,
          profile,
          manifest_sha256: data.manifest_sha256,
          license_accepted: true,
        }),
      );
    },
    onSuccess: refresh,
  });
  const ready = data?.existing_images?.available === true;
  const configured = data?.existing_images?.source === "configured";
  const existing = history.data?.some(
    (row) =>
      !terminal.has(row.run.status) ||
      (row.resume_allowed && row.manifest_sha256 === data?.manifest_sha256),
  );
  const storageFits =
    !data?.storage || data.storage.free_bytes >= data.storage.required_bytes;
  return (
    <section
      className="panel setup-runtime setup-images"
      aria-label="Local image setup"
      ref={section}
    >
      <div className="speech-setup-heading">
        <div className="speech-setup-icon">
          <ImagePlus size={24} />
        </div>
        <div>
          <h2>Images & photo editing</h2>
          <p className="muted">
            Turn an idea into an image. Edit, recompose and upscale locally,
            with your originals and results kept together.
          </p>
        </div>
        {ready && (
          <span className="setup-fit">
            <Check size={14} /> Ready
          </span>
        )}
      </div>
      {!expanded ? (
        <Button variant="secondary" onClick={() => setOpened(true)}>
          Set up images <ArrowRight size={15} />
        </Button>
      ) : (
        <>
          <ErrorNotice
            error={catalog.error ?? history.error ?? prepare.error}
          />
          {catalog.isPending ? (
            <Loading />
          ) : !data?.recipe ? (
            <p className="notice">
              Image setup could not be inspected.{" "}
              <Link to="/system">Open Diagnostics</Link>
            </p>
          ) : (
            <>
              {ready && (
                <div className="speech-setup-ready">
                  <p>
                    <strong>Your image integration is ready.</strong> Open
                    Images to create a new picture or work with a reference.
                  </p>
                  <Button asChild>
                    <Link to="/images">
                      Open Images <ArrowRight size={15} />
                    </Link>
                  </Button>
                  {data.can_prepare && (
                    <button
                      type="button"
                      className="text-link"
                      onClick={() => setShowManaged(!showManaged)}
                    >
                      {showManaged
                        ? "Hide managed installation"
                        : configured
                          ? "Advanced: install a managed copy"
                          : "Review installation"}
                    </button>
                  )}
                </div>
              )}
              {(!ready || showManaged) && (
                <>
                  <div className="speech-setup-facts">
                    <div>
                      <small>IMAGE MODELS</small>
                      <strong>{data.recipe.name} + RealESRGAN</strong>
                    </div>
                    <div>
                      <small>COMPLETE DOWNLOAD</small>
                      <strong>{size(data.storage?.download_bytes ?? 0)}</strong>
                    </div>
                    <div>
                      <small>HARDWARE</small>
                      <strong>2 NVIDIA GPUs · 12 GiB VRAM each</strong>
                    </div>
                  </div>
                  <p className="muted setup-small">
                    Models and engine run on this workstation. Generation
                    reserves both GPUs; Upscale uses one.
                  </p>
                  {data.hardware?.gpus.length ? (
                    <p className="muted setup-small">
                      Detected:{" "}
                      {data.hardware.gpus
                        .map(
                          (gpu) =>
                            `${gpu.name ?? `GPU ${gpu.index}`}${gpu.memory_total_mib ? ` (${(gpu.memory_total_mib / 1024).toFixed(1)} GiB)` : ""}`,
                        )
                        .join(" · ")}
                    </p>
                  ) : null}
                  {data.storage && (
                    <p className="muted setup-small">
                      {size(data.storage.free_bytes)} free in application
                      storage · {size(data.storage.required_bytes)} needed.{" "}
                      {size(data.storage.cached_model_bytes_estimate)} of model
                      files already present; setup verifies them before reuse.
                      {data.storage.docker_required_bytes > 0 &&
                        ` The image engine also needs ${size(data.storage.docker_required_bytes)} free in Docker storage${data.storage.docker_free_bytes === null ? " (space could not be inspected)" : ` (${size(data.storage.docker_free_bytes)} available)`}.`}
                    </p>
                  )}
                  {configured && (
                    <p className="notice">
                      Your configured image integration keeps its settings. This
                      prepares an additional managed copy.
                      {!ready &&
                        " The existing integration needs attention; check Diagnostics before switching."}
                    </p>
                  )}
                  <details className="speech-setup-sources">
                    <summary>Models, sources and licenses</summary>
                    <p className="setup-small muted">
                      Qwen model weights use the Qwen Research License. The
                      encoder, upscaler and engine have separate licenses.
                      Review each component before downloading.
                    </p>
                    <div className="speech-setup-license-links">
                      {data.licenses?.map((item) => (
                        <a
                          key={item.url}
                          href={item.url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {item.name}
                        </a>
                      ))}
                    </div>
                    <ul>
                      {data.recipe.inputs.map((item) => (
                        <li key={item.sha256}>
                          <span>
                            <a href={item.url} target="_blank" rel="noreferrer">
                              {item.filename}
                            </a>
                            <br />
                            <small className="muted">
                              {item.role.replaceAll("_", " ")}
                            </small>
                          </span>
                          <small className="muted">
                            {size(item.size_bytes)}
                          </small>
                        </li>
                      ))}
                    </ul>
                  </details>
                  {!data.can_prepare ? (
                    <p className="notice">
                      Your administrator can install shared image models. Your
                      prompts, reference images and results stay private.
                    </p>
                  ) : (
                    !existing && (
                      <>
                        {!data.installation_available && (
                          <p className="notice">
                            {data.installation_notice ??
                              "This image profile is not available on this workstation."}{" "}
                            <Link to="/system">View Diagnostics</Link>
                          </p>
                        )}
                        {!storageFits && (
                          <p className="notice">
                            More free storage is needed before image setup can
                            begin.
                          </p>
                        )}
                        <label className="setup-license">
                          <input
                            type="checkbox"
                            checked={accepted === data.manifest_sha256}
                            disabled={
                              !data.installation_available || prepare.isPending
                            }
                            onChange={(event) =>
                              setAccepted(
                                event.target.checked
                                  ? data.manifest_sha256
                                  : "",
                              )
                            }
                          />
                          <span>
                            I have reviewed the image model and bundled
                            component licenses.
                          </span>
                        </label>
                        <Button
                          disabled={
                            !data.installation_available ||
                            !storageFits ||
                            accepted !== data.manifest_sha256 ||
                            prepare.isPending
                          }
                          onClick={() => prepare.mutate()}
                        >
                          <Download size={16} />{" "}
                          {prepare.isPending
                            ? "Starting image setup…"
                            : ready && !configured
                              ? "Verify image installation"
                              : "Download & set up images"}
                        </Button>
                      </>
                    )
                  )}
                </>
              )}
            </>
          )}
          {history.data?.map((value) => (
            <ImagePreparation
              key={value.id}
              value={value}
              canPrepare={data?.can_prepare ?? false}
              available={data?.installation_available ?? false}
              ready={ready}
              manifest={data?.manifest_sha256}
              refresh={refresh}
            />
          ))}
        </>
      )}
    </section>
  );
}
