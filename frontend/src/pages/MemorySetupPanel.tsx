import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowRight, Brain, Check, Download, Square } from "lucide-react";
import { api, type Run } from "../api";
import { Badge, ErrorNotice, Loading } from "../components/common";
import { Button } from "../components/ui/button";

const terminal = new Set(["succeeded", "failed", "canceled", "interrupted"]);
const active = (run?: Run | null) => !!run && !terminal.has(run.status);
const size = (bytes: number) => `${(bytes / 1024 ** 2).toFixed(0)} MiB`;
type Setup = {
  can_prepare: boolean;
  configured: boolean;
  backend: string;
  model: string;
  revision: number;
  local_model: {
    id: string;
    name: string;
    revision: string;
    license: string;
    source_url: string;
    size_bytes: number;
    available: boolean;
    installed: boolean;
    storage: {
      free_bytes: number;
      required_bytes: number;
      cached_bytes_estimate: number;
    };
    files: {
      filename: string;
      url: string;
      size_bytes: number;
      sha256: string;
    }[];
  };
  prepare_run?: Run | null;
  index_run?: Run | null;
  health_run?: Run | null;
};

export default function MemorySetupPanel() {
  const [search] = useSearchParams();
  const [opened, setOpened] = useState(false);
  const [replace, setReplace] = useState(false);
  const [accepted, setAccepted] = useState("");
  const section = useRef<HTMLElement>(null);
  const cache = useQueryClient();
  const expanded = opened || search.get("capability") === "memory";
  const setup = useQuery({
    queryKey: ["memory-embeddings"],
    queryFn: () => api<Setup>("/memory/embeddings/setup"),
    enabled: expanded,
    refetchInterval: (query) =>
      [
        query.state.data?.prepare_run,
        query.state.data?.index_run,
        query.state.data?.health_run,
      ].some(active)
        ? 1000
        : false,
  });
  const data = setup.data;
  const local = data?.local_model;
  const external = !!data?.configured && data.backend !== "local_cpu";
  const ready =
    !!data?.configured &&
    (external || (local?.installed === true && local.available === true));
  const running = [data?.prepare_run, data?.index_run, data?.health_run].find(
    active,
  );
  const last = running ?? data?.prepare_run;
  const storageFits =
    !!local && local.storage.free_bytes >= local.storage.required_bytes;
  const consent = local ? `${local.id}:${local.revision}` : "";
  const refresh = () =>
    void cache.invalidateQueries({ queryKey: ["memory-embeddings"] });
  const action = useMutation({
    mutationFn: (kind: "prepare" | "stop") => {
      if (kind === "stop") {
        if (!running) throw new Error("No active memory setup to stop");
        return api<Run>(`/runs/${running.id}/cancel`, { method: "POST" });
      }
      if (
        !data?.can_prepare ||
        !local?.available ||
        !storageFits ||
        running ||
        (!local.installed && accepted !== consent)
      )
        throw new Error(
          "Review the memory model and available storage before setup",
        );
      return api<Run>("/memory/embeddings/prepare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model_id: local.id,
          expected_revision: data.revision,
          confirm_download: !local.installed,
        }),
      });
    },
    onSettled: refresh,
  });
  useEffect(() => {
    if (expanded && search.get("capability") === "memory")
      section.current?.scrollIntoView?.({ block: "start", behavior: "smooth" });
  }, [expanded, search]);
  const download = running?.metadata?.embedding_download as
    | { file: string; received_bytes: number; expected_bytes: number }
    | undefined;
  return (
    <section
      className="panel setup-runtime setup-memory"
      aria-label="Local memory setup"
      ref={section}
    >
      <div className="speech-setup-heading">
        <div className="speech-setup-icon">
          <Brain size={24} />
        </div>
        <div>
          <h2>Memory & search</h2>
          <p className="muted">
            Find saved knowledge by meaning, across languages. Runs on your CPU
            and leaves the GPUs free.
          </p>
        </div>
        {ready && (
          <span className={external ? "muted setup-small" : "setup-fit"}>
            {!external && <Check size={14} />}
            {external ? "Endpoint configured" : "Ready"}
          </span>
        )}
      </div>
      {!expanded ? (
        <Button variant="secondary" onClick={() => setOpened(true)}>
          Set up memory <ArrowRight size={15} />
        </Button>
      ) : (
        <>
          <ErrorNotice error={setup.error ?? action.error} />
          {setup.isPending ? (
            <Loading />
          ) : !local ? (
            <p className="notice">
              Memory setup could not be inspected.{" "}
              <Link to="/memory">Open Memory</Link>
            </p>
          ) : (
            <>
              {ready && (
                <div className="speech-setup-ready">
                  <p>
                    <strong>Memory search is configured.</strong>{" "}
                    {external
                      ? `Your existing endpoint (${data.model}) stays selected.`
                      : `${local.name} is installed locally.`}
                  </p>
                  <Button asChild>
                    <Link to="/memory">
                      Open Memory <ArrowRight size={15} />
                    </Link>
                  </Button>
                  {external && data.can_prepare && (
                    <button
                      className="text-link"
                      onClick={() => setReplace(!replace)}
                    >
                      {replace
                        ? "Keep existing endpoint"
                        : "Use a local CPU model instead"}
                    </button>
                  )}
                </div>
              )}
              {(!ready || replace) && (
                <>
                  <div className="speech-setup-facts">
                    <div>
                      <small>MEMORY MODEL</small>
                      <strong>{local.name} · INT8</strong>
                    </div>
                    <div>
                      <small>DOWNLOAD</small>
                      <strong>{size(local.size_bytes)}</strong>
                    </div>
                    <div>
                      <small>HARDWARE</small>
                      <strong>CPU · no GPU required</strong>
                    </div>
                  </div>
                  <p className="muted setup-small">
                    Two CPU threads · up to 2 GiB RAM per operation. Model files
                    are shared; your memories, search results and setup history
                    stay private.
                  </p>
                  <p className="muted setup-small">
                    {size(local.storage.free_bytes)} free ·{" "}
                    {size(local.storage.required_bytes)} needed.{" "}
                    {size(local.storage.cached_bytes_estimate)} of model files
                    already present; complete files are verified before reuse.
                  </p>
                  <details className="speech-setup-sources">
                    <summary>Model, sources and license</summary>
                    <p className="muted setup-small">
                      <a
                        href={local.source_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {local.name} · {local.license} license
                      </a>
                      . Downloaded weights stay on this station; memory content
                      is never sent to the publisher.
                    </p>
                    <ul>
                      {local.files.map((file) => (
                        <li key={file.sha256}>
                          <a href={file.url} target="_blank" rel="noreferrer">
                            {file.filename}
                          </a>
                          <small className="muted">
                            {size(file.size_bytes)}
                          </small>
                        </li>
                      ))}
                    </ul>
                  </details>
                  {!data.can_prepare ? (
                    <p className="notice">
                      Your administrator can install or configure the shared
                      memory model. You can use Memory once it is ready.
                    </p>
                  ) : (
                    !running && (
                      <>
                        {!local.available && (
                          <p className="notice">
                            This application image does not include the CPU
                            embedding engine.{" "}
                            <Link to="/system">Open Diagnostics</Link>
                          </p>
                        )}
                        {!storageFits && (
                          <p className="notice">
                            More free application storage is required before
                            memory setup.
                          </p>
                        )}
                        {external && (
                          <p className="notice">
                            This explicitly replaces the configured embedding
                            endpoint. Existing memory text is kept; the local
                            model builds a new index.
                          </p>
                        )}
                        {!local.installed && (
                          <label className="setup-license">
                            <input
                              type="checkbox"
                              checked={accepted === consent}
                              disabled={
                                action.isPending ||
                                !local.available ||
                                !storageFits
                              }
                              onChange={(event) =>
                                setAccepted(event.target.checked ? consent : "")
                              }
                            />
                            <span>
                              I have reviewed the memory model source and MIT
                              license and agree to download{" "}
                              {size(local.size_bytes)}.
                            </span>
                          </label>
                        )}
                        <Button
                          disabled={
                            action.isPending ||
                            !local.available ||
                            !storageFits ||
                            (!local.installed && accepted !== consent)
                          }
                          onClick={() => action.mutate("prepare")}
                        >
                          <Download size={16} />
                          {action.isPending
                            ? "Starting memory setup…"
                            : local.installed
                              ? "Use local memory model"
                              : "Download & set up memory"}
                        </Button>
                      </>
                    )
                  )}
                </>
              )}
              {last && (
                <article
                  className="setup-runtime-attempt"
                  aria-label="Memory setup activity"
                >
                  <div className="row spread">
                    <strong>
                      {running
                        ? running.capability === "memory.embed.index"
                          ? "Indexing your memories"
                          : running.status === "cancel_requested"
                            ? "Stopping safely…"
                            : download
                              ? "Downloading memory model"
                              : "Checking the memory engine"
                        : last.status === "succeeded"
                          ? "Memory model prepared"
                          : "Preparation needs attention"}
                    </strong>
                    <Badge status={last.status} />
                  </div>
                  {running &&
                    (download?.expected_bytes ? (
                      <>
                        <progress
                          aria-label="Memory model download progress"
                          value={Math.max(
                            0,
                            Math.min(
                              download.received_bytes,
                              download.expected_bytes,
                            ),
                          )}
                          max={download.expected_bytes}
                        />
                        <p className="muted setup-small">
                          {size(download.received_bytes)} of{" "}
                          {size(download.expected_bytes)} · {download.file}
                        </p>
                      </>
                    ) : (
                      <progress aria-label="Memory model preparation" />
                    ))}
                  {running && (
                    <p className="muted setup-small">
                      You can leave this page. Progress is saved.
                    </p>
                  )}
                  {!running && last.error_message && (
                    <p className="notice">{last.error_message}</p>
                  )}
                  <div className="row speech-setup-actions">
                    {data.can_prepare && running && (
                      <Button
                        variant="secondary"
                        disabled={
                          action.isPending ||
                          running.status === "cancel_requested"
                        }
                        onClick={() => action.mutate("stop")}
                      >
                        <Square size={14} /> Stop memory setup
                      </Button>
                    )}
                    <Link className="text-link" to={`/runs/${last.id}`}>
                      View details
                    </Link>
                    <Link className="text-link" to="/memory">
                      Search and manage memory
                    </Link>
                  </div>
                  {!running &&
                    ["failed", "canceled", "interrupted"].includes(
                      last.status,
                    ) && (
                      <p className="muted setup-small">
                        Start setup again to reuse verified complete files. An
                        unfinished file is downloaded again.
                      </p>
                    )}
                </article>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
