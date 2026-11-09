import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, RefreshCw, Download } from "lucide-react";
import { useEffect, useRef } from "react";
import Markdown from "react-markdown";
import { Link } from "react-router-dom";
import { api, type Run } from "../api";
import { ErrorNotice, Loading } from "../components/common";
import { Button } from "../components/ui/button";
import { randomId } from "../lib/random-id";
import { version as buildVersion } from "../../package.json";
import { newerVersion, type UpdateStatus } from "./station-update-contract";
import "./StationUpdates.css";

const active = new Set([
  "queued",
  "claimed",
  "preparing",
  "running",
  "cancel_requested",
]);

export default function StationUpdates() {
  const cache = useQueryClient();
  const query = useQuery({
    queryKey: ["station-updates"],
    queryFn: () => api<UpdateStatus>("/maintenance/updates"),
    refetchInterval: (query) =>
      active.has(query.state.data?.latest_check?.status ?? "") ||
      active.has(query.state.data?.update_run?.status ?? "")
        ? 1500
        : false,
  });
  const check = useMutation({
    mutationFn: () =>
      api<Run>("/maintenance/updates/checks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      }),
    onSuccess: () => cache.invalidateQueries({ queryKey: ["station-updates"] }),
  });
  const requestId = useRef<string | null>(null);
  const install = useMutation({
    mutationFn: () => {
      requestId.current ??= randomId();
      return api<Run>("/maintenance/updates/install", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          check_run_id: query.data?.release_check_run_id,
          fingerprint: query.data?.release?.fingerprint,
          client_request_id: requestId.current,
        }),
      });
    },
    onSuccess: () => {
      requestId.current = null;
      return cache.invalidateQueries({ queryKey: ["station-updates"] });
    },
  });
  const cancel = useMutation({
    mutationFn: () =>
      api(`/runs/${query.data?.update_run?.id}/cancel`, { method: "POST" }),
    onSuccess: () => cache.invalidateQueries({ queryKey: ["station-updates"] }),
  });
  const data = query.data;
  const updating = active.has(data?.update_run?.status ?? "");
  const restarting =
    updating && !!data?.update_run?.metadata?.update_apply_requested;
  const checking =
    check.isPending || active.has(data?.latest_check?.status ?? "");
  const busy =
    check.isPending ||
    install.isPending ||
    updating ||
    active.has(data?.latest_check?.status ?? "");
  const native = data?.update_run?.metadata?.native_update;
  const inspected = data?.update_run?.status === "interrupted";
  const download = data?.release?.packages?.[data.installation?.platform ?? ""];
  useEffect(() => {
    if (!data?.current_version) return;
    cache.setQueryData(["station-version"], { version: data.current_version });
    if (
      data.update_run?.status === "succeeded" &&
      data.current_version !== buildVersion
    )
      window.location.reload();
  }, [data?.current_version, data?.update_run?.status, cache]);
  const available =
    data?.release && newerVersion(data.release.version, data.current_version);
  const failed = data?.latest_check?.status === "failed";
  return (
    <section className="panel station-updates">
      <div className="panel-heading">
        <div>
          <h2>App updates</h2>
          <p className="muted">
            Keep your station up to date. Your models and saved work stay in
            place.
          </p>
        </div>
        <Button
          variant="secondary"
          disabled={busy || query.isPending}
          onClick={() => check.mutate()}
        >
          <RefreshCw size={15} aria-hidden="true" />
          {checking ? "Checking…" : "Check for updates"}
        </Button>
      </div>
      <ErrorNotice
        error={
          (restarting ? null : query.error) ??
          check.error ??
          install.error ??
          cancel.error
        }
      />
      {query.isPending ? (
        <Loading />
      ) : (
        data && (
          <div className="station-update-body">
            <div className="station-update-summary" role="status">
              <span className="station-update-version">
                v{data.current_version}
              </span>
              <div>
                <strong>
                  {updating
                    ? "Updating your station"
                    : check.isPending ||
                        active.has(data.latest_check?.status ?? "")
                      ? "Looking for a newer version"
                      : available
                        ? `AI Station ${data.release!.version} is available`
                        : data.release
                          ? "You’re up to date"
                          : "Ready to check"}
                </strong>
                <p className="muted">
                  {data.checked_at
                    ? `Last checked ${new Date(data.checked_at).toLocaleString()}`
                    : "Checks the official AI Station stable release on GitHub."}
                </p>
              </div>
            </div>
            {updating && (
              <div className="station-update-progress" role="status">
                <strong>
                  {restarting
                    ? query.error
                      ? "Reconnecting to your updated station…"
                      : "Installing and restarting…"
                    : native?.phase === "ready"
                      ? "Waiting for your current work to finish"
                      : native?.phase === "downloading"
                        ? "Downloading the verified update"
                        : "Preparing your update"}
                </strong>
                <p className="muted">
                  {restarting
                    ? "The page reconnects automatically. Your saved work stays in place."
                    : "You can keep using AI Station while the package downloads. Active tasks will finish before the restart."}
                </p>
                {!!native?.size_bytes && (
                  <progress
                    aria-label="Update download progress"
                    value={native.downloaded_bytes ?? 0}
                    max={native.size_bytes}
                  />
                )}
                {!restarting && (
                  <Button
                    variant="ghost"
                    disabled={
                      cancel.isPending ||
                      data.update_run?.status === "cancel_requested"
                    }
                    onClick={() => cancel.mutate()}
                  >
                    {cancel.isPending ||
                    data.update_run?.status === "cancel_requested"
                      ? "Canceling…"
                      : "Cancel update"}
                  </Button>
                )}
              </div>
            )}
            {inspected && (
              <p role="alert">
                This update needs inspection before another attempt. Your saved
                data and previous package are retained. Open the update details
                below.
              </p>
            )}
            {data.update_run?.status === "failed" && (
              <p role="alert">
                {data.update_run.error_message ||
                  "The update could not be prepared. Your current version keeps working."}
              </p>
            )}
            {available &&
              data.apply_available &&
              data.release_check_run_id &&
              data.release?.fingerprint &&
              !inspected &&
              !updating && (
                <div className="station-update-action">
                  <Button disabled={busy} onClick={() => install.mutate()}>
                    <Download size={16} aria-hidden="true" />
                    {install.isPending
                      ? "Starting update…"
                      : "Update and restart"}
                  </Button>
                  <p className="muted">
                    {download
                      ? `${Math.ceil(download.size_bytes / 1024 ** 2)} MB download. `
                      : ""}
                    Accounts, models, conversations and files are preserved.
                  </p>
                </div>
              )}
            {failed && (
              <p role="alert">
                {data.latest_check?.error_message ||
                  "Couldn’t check for updates. Your current version keeps working."}
              </p>
            )}
            {available && (
              <div className="station-update-release">
                <h3>What’s new</h3>
                <div className="station-release-notes">
                  <Markdown
                    skipHtml
                    allowedElements={[
                      "p",
                      "strong",
                      "em",
                      "ul",
                      "ol",
                      "li",
                      "h2",
                      "h3",
                      "h4",
                      "code",
                      "pre",
                      "a",
                      "hr",
                      "blockquote",
                    ]}
                    unwrapDisallowed
                    components={{
                      img: () => null,
                      a: ({ children, href }) => (
                        <a
                          href={href}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {children}
                        </a>
                      ),
                    }}
                  >
                    {data.release!.notes ||
                      "See the official release for details."}
                  </Markdown>
                </div>
                <a
                  href={data.release!.release_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  View official release{" "}
                  <ArrowUpRight size={14} aria-hidden="true" />
                </a>
              </div>
            )}
            <div className="station-update-links">
              {data.latest_check && (
                <Link className="muted" to={`/runs/${data.latest_check.id}`}>
                  View update check
                </Link>
              )}
              {data.update_run && (
                <Link
                  className="station-update-details"
                  to={`/runs/${data.update_run.id}`}
                >
                  View update details
                </Link>
              )}
            </div>
          </div>
        )
      )}
    </section>
  );
}
