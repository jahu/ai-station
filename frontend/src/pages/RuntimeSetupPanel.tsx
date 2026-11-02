import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Box, Check, Download, RotateCcw, Square } from "lucide-react";
import { api, type Run } from "../api";
import { ErrorNotice, Badge } from "../components/common";
import { Button } from "../components/ui/button";
import { randomId } from "../lib/random-id";

type Recipe = {
  profile: string;
  name?: string;
  download_bytes?: number;
  inputs?: { size_bytes: number }[];
  source_revision?: string;
  release?: string;
  license: string;
  license_url: string;
  cuda_license_url?: string;
  image_reference?: string;
};
type Catalog = {
  can_prepare: boolean;
  usable_image?: boolean;
  sdk_prepared?: boolean;
  installation_available: boolean;
  installation_notice?: string;
  manifest_sha256: string;
  recipe?: Recipe;
  storage?: { free_bytes: number; required_bytes: number } | null;
};
type Preparation = {
  id: string;
  recipe: Recipe;
  attempt: number;
  run: Run;
  resume_allowed: boolean;
  progress: {
    phase?: string;
    received_bytes?: number;
    expected_bytes?: number;
  };
};
const terminal = new Set(["succeeded", "failed", "canceled", "interrupted"]);
const json = (value: unknown) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(value),
});
const size = (bytes: number) =>
  bytes >= 1024 ** 3
    ? `${(bytes / 1024 ** 3).toFixed(2)} GiB`
    : `${(bytes / 1024 ** 2).toFixed(1)} MiB`;

const nativeProfile = (profile: string) =>
  profile.startsWith("llamacpp-native-darwin-");
const downloadBytes = (recipe: Recipe) =>
  recipe.download_bytes ??
  recipe.inputs?.reduce((total, item) => total + item.size_bytes, 0) ??
  0;

function RuntimePreparation({
  value,
  canPrepare,
  refresh,
}: {
  value: Preparation;
  canPrepare: boolean;
  refresh: () => void;
}) {
  const receipt = useRef<{ run: string; id: string } | null>(null);
  const active = !terminal.has(value.run.status);
  const action = useMutation({
    mutationFn: (kind: "cancel" | "resume") => {
      if (!receipt.current || receipt.current.run !== value.run.id)
        receipt.current = { run: value.run.id, id: randomId() };
      return api(
        `/setup/runtimes/preparations/${value.id}/${kind}`,
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
  const native = nativeProfile(value.recipe.profile);
  const expected = value.progress.expected_bytes ?? downloadBytes(value.recipe);
  const received = Math.max(
    0,
    Math.min(expected, value.progress.received_bytes ?? 0),
  );
  const label =
    value.run.status === "succeeded"
      ? native
        ? "Native engine prepared"
        : "Runtime image verified"
      : value.run.status === "canceled"
        ? native
          ? "Stopped · downloaded files are kept"
          : "Stopped · cached layers are kept"
        : value.run.status === "queued"
          ? "Queued"
          : value.progress.phase === "unpacking"
            ? native
              ? "Preparing the native engine"
              : "Preparing downloaded layers"
            : value.progress.phase === "verifying"
              ? native
                ? "Checking the native engine"
                : "Checking the runtime image"
              : value.run.status === "cancel_requested"
                ? "Stopping the transfer"
                : active
                  ? "Preparing llama.cpp"
                  : "Preparation needs attention";
  return (
    <article
      id={`runtime-preparation-${value.id}`}
      tabIndex={-1}
      className="setup-runtime-attempt"
      aria-label={`Runtime preparation ${value.id.slice(0, 8)}`}
    >
      <div className="row spread">
        <strong>{label}</strong>
        <Badge status={value.run.status} />
      </div>
      <p className="muted setup-small">
        Attempt {value.attempt} ·{" "}
        {new Date(value.run.created_at).toLocaleString()}
      </p>
      {active && (
        <>
          <progress
            aria-label="Runtime preparation progress"
            max={expected}
            value={received}
          />
          <p className="muted setup-small">
            {size(received)} of {size(expected)} prepared, including reused
            {native ? "files" : "layers"}.
          </p>
        </>
      )}
      {value.run.error_message && (
        <p className="notice" role="alert">
          {value.run.error_message}
        </p>
      )}
      <ErrorNotice error={action.error} />
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
            Stop runtime preparation
          </Button>
        )}
        {value.resume_allowed && canPrepare && (
          <Button
            variant="secondary"
            disabled={action.isPending}
            onClick={() => action.mutate("resume")}
          >
            <RotateCcw size={14} />
            Resume runtime preparation
          </Button>
        )}
        <Link className="text-link" to={`/runs/${value.run.id}`}>
          Details & logs
        </Link>
      </div>
    </article>
  );
}

export default function RuntimeSetupPanel({
  onReadiness,
  profile = "llamacpp-cuda-linux-amd64-v1",
}: {
  profile?: string;
  onReadiness: (ready: boolean | undefined) => void;
}) {
  const cache = useQueryClient();
  const native = nativeProfile(profile);
  const cpu = native || profile === "llamacpp-cpu-linux-amd64-v1";
  const profileSpecific = profile !== "llamacpp-cuda-linux-amd64-v1";
  const suffix = profileSpecific
    ? "?profile=" + encodeURIComponent(profile)
    : "";
  const catalog = useQuery({
    queryKey: profileSpecific
      ? ["runtime-setup-catalog", profile]
      : ["runtime-setup-catalog"],
    queryFn: () => api<Catalog>("/setup/runtimes" + suffix),
  });
  const history = useQuery({
    queryKey: profileSpecific
      ? ["runtime-preparations", profile]
      : ["runtime-preparations"],
    queryFn: () => api<Preparation[]>("/setup/runtimes/preparations" + suffix),
    refetchInterval: (query) =>
      query.state.data?.some((row) => !terminal.has(row.run.status))
        ? 1000
        : false,
  });
  const [accepted, setAccepted] = useState("");
  const token = useRef<{ hash: string; id: string } | null>(null);
  const completed = useRef(new Set<string>());
  const data = catalog.data,
    recipe = data?.recipe;
  const ready = native ? data?.sdk_prepared : data?.usable_image;
  const active = history.data?.find((row) => !terminal.has(row.run.status));
  const existing = history.data?.find(
    (row) =>
      row.recipe.profile === recipe?.profile &&
      (!terminal.has(row.run.status) || row.resume_allowed),
  );
  useEffect(() => {
    if (ready) token.current = null;
  }, [ready]);
  useEffect(() => {
    onReadiness(typeof ready === "boolean" ? ready : undefined);
  }, [ready, onReadiness]);
  useEffect(() => {
    for (const row of history.data ?? [])
      if (
        row.run.status === "succeeded" &&
        !completed.current.has(row.run.id)
      ) {
        completed.current.add(row.run.id);
        void cache.invalidateQueries({ queryKey: ["runtime-setup-catalog"] });
        void cache.invalidateQueries({ queryKey: ["setup-catalog"] });
        void cache.invalidateQueries({ queryKey: ["models"] });
      }
  }, [history.data, cache]);
  const refresh = () => {
    void cache.invalidateQueries({ queryKey: ["runtime-preparations"] });
    void cache.invalidateQueries({ queryKey: ["runtime-setup-catalog"] });
  };
  const prepare = useMutation({
    mutationFn: () => {
      if (!recipe || !data || accepted !== data.manifest_sha256)
        throw new Error("Review the runtime licenses before preparing.");
      if (!token.current || token.current.hash !== data.manifest_sha256)
        token.current = { hash: data.manifest_sha256, id: randomId() };
      return api(
        "/setup/runtimes",
        json({
          client_request_id: token.current.id,
          profile: recipe.profile,
          manifest_sha256: data.manifest_sha256,
          license_accepted: true,
        }),
      );
    },
    onSuccess: refresh,
  });
  if (!recipe && !catalog.error)
    return data?.installation_notice ? (
      <section className="panel setup-runtime">
        <p className="muted">{data.installation_notice}</p>
      </section>
    ) : null;
  return (
    <section
      className="panel setup-runtime"
      aria-label="Conversation engine setup"
    >
      <div className="row spread">
        <div className="row">
          <Box size={20} />
          <h2>Local conversation engine</h2>
        </div>
        {ready && (
          <span className="setup-fit">
            <Check size={14} />
            {native ? "Native engine available" : "Image available"}
          </span>
        )}
      </div>
      <p className="muted">
        {ready
          ? "llama.cpp is available. Choose a local model below; it loads when you send a message."
          : "First prepare llama.cpp, then choose your local model below."}
      </p>
      {cpu && (
        <p className="muted setup-small">
          {native ? "Native Mac CPU execution" : "CPU execution"} · no NVIDIA
          GPU needed. This uses system RAM and is slower than GPU inference.
        </p>
      )}
      <ErrorNotice error={catalog.error ?? history.error ?? prepare.error} />
      {!ready && recipe && (
        <>
          <p>
            {size(downloadBytes(recipe))} download · runs locally on this
            station.
          </p>
          {data?.storage && (
            <p className="muted setup-small">
              {size(data.storage.free_bytes)} free in runtime storage ·{" "}
              {size(data.storage.required_bytes)} needed during preparation.
            </p>
          )}
          <details>
            <summary>Runtime source and licenses</summary>
            <p>
              <a href={recipe.license_url} target="_blank" rel="noreferrer">
                llama.cpp license
              </a>
              {recipe.cuda_license_url && (
                <>
                  {" "}
                  ·{" "}
                  <a
                    href={recipe.cuda_license_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    CUDA component terms
                  </a>
                </>
              )}
            </p>
            <p className="setup-small muted">{recipe.license}</p>
            <p className="setup-small model-path">
              {native
                ? `${recipe.release ?? "llama.cpp"} · ${recipe.source_revision ?? ""}`
                : recipe.image_reference}
            </p>
          </details>
          {!data?.can_prepare ? (
            <p className="notice">
              Your administrator prepares shared runtimes. Existing models
              remain available in Chat.
            </p>
          ) : (
            !existing && (
              <>
                {!data.installation_available && (
                  <p className="notice">
                    {data.installation_notice ||
                      "Runtime preparation is not available yet."}
                  </p>
                )}
                <label className="setup-license">
                  <input
                    type="checkbox"
                    checked={accepted === data.manifest_sha256}
                    onChange={(e) =>
                      setAccepted(e.target.checked ? data.manifest_sha256 : "")
                    }
                    disabled={prepare.isPending || !data.installation_available}
                  />
                  <span>
                    I have reviewed the runtime and bundled component licenses.
                  </span>
                </label>
                <Button
                  disabled={
                    !data.installation_available ||
                    accepted !== data.manifest_sha256 ||
                    prepare.isPending
                  }
                  onClick={() => prepare.mutate()}
                >
                  <Download size={16} />
                  {prepare.isPending ? "Queuing…" : "Prepare llama.cpp"}
                </Button>
              </>
            )
          )}
        </>
      )}
      {existing && !ready && (
        <Button
          variant="secondary"
          onClick={() => {
            const card = document.getElementById(
              `runtime-preparation-${existing.id}`,
            );
            card?.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
            card?.focus({ preventScroll: true });
          }}
        >
          View existing runtime preparation
        </Button>
      )}
      {!!history.data?.length && (
        <details open={Boolean(active) || !ready}>
          <summary>Runtime preparation history</summary>
          {history.data.map((row) => (
            <RuntimePreparation
              key={row.id}
              value={row}
              canPrepare={data?.can_prepare ?? false}
              refresh={refresh}
            />
          ))}
        </details>
      )}
    </section>
  );
}
