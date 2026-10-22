import { useEffect, useRef, useState, type MouseEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import {
  ArrowDown,
  ArrowUp,
  ExternalLink,
  Monitor,
  Play,
  RotateCcw,
  Smartphone,
  X,
} from "lucide-react";
import { api, type Run } from "../api";
import { Button } from "../components/ui/button";
import { randomId } from "../lib/random-id";
import "./SitePreview.css";

type Frame = {
  artifact_id: string;
  revision: number;
  width: number;
  height: number;
  title: string;
  path: string;
  blocked_requests: number;
};
type Action =
  | { kind: "click"; x: number; y: number }
  | { kind: "text"; text: string }
  | { kind: "key"; key: string }
  | { kind: "scroll"; delta_x: number; delta_y: number }
  | { kind: "reset" | "snapshot" };
const terminal = new Set(["succeeded", "failed", "canceled", "interrupted"]);
const keys = new Set([
  "Tab",
  "Enter",
  "Escape",
  "Backspace",
  "Delete",
  "ArrowUp",
  "ArrowDown",
  "ArrowLeft",
  "ArrowRight",
  "Home",
  "End",
  "PageUp",
  "PageDown",
  " ",
]);
class PreviewRequestError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
async function post(path: string, body: unknown): Promise<Run> {
  const response = await fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const value = await response.json().catch(() => ({}));
    throw new PreviewRequestError(
      typeof value.detail === "string"
        ? value.detail
        : `Preview request failed (${response.status})`,
      response.status,
    );
  }
  return response.json();
}
const rejected = (error: Error) =>
  error instanceof PreviewRequestError &&
  error.status >= 400 &&
  error.status < 500;

export default function SitePreview() {
  const { sourceRunId, artifactId } = useParams();
  return (
    <PreviewSession
      key={`${sourceRunId}:${artifactId}`}
      sourceRunId={sourceRunId}
      artifactId={artifactId}
    />
  );
}

function PreviewSession({
  sourceRunId,
  artifactId,
}: {
  sourceRunId?: string;
  artifactId?: string;
}) {
  const cache = useQueryClient();
  const [selected, setSelected] = useState<string>();
  const [profile, setProfile] = useState("desktop");
  const [text, setText] = useState("");
  const [pendingId, setPendingId] = useState<string>();
  // Preserve the same receipt across an ambiguous HTTP failure. Retry never means a second click.
  const openReceipt = useRef<Record<string, unknown> | null>(null);
  const actionReceipt = useRef<Record<string, unknown> | null>(null);
  const closeReceipt = useRef<Record<string, unknown> | null>(null);
  const source = useQuery({
    queryKey: ["run", sourceRunId],
    queryFn: () => api<Run>(`/runs/${sourceRunId}`),
    enabled: !!sourceRunId,
  });
  const caps = useQuery({
    queryKey: ["site-preview-capabilities"],
    queryFn: () =>
      api<{ available: boolean; reason?: string }>(
        "/site-previews/capabilities",
      ),
  });
  const sessions = useQuery({
    queryKey: ["site-previews", source.data?.task_id],
    queryFn: () =>
      api<Run[]>(`/site-previews?source_task_id=${source.data!.task_id}`),
    enabled: !!source.data?.task_id,
  });
  const last = sessions.data?.find(
    (run) =>
      (run.parameters.source as { artifact_id?: string })?.artifact_id ===
      artifactId,
  );
  const id = selected ?? last?.id;
  const preview = useQuery({
    queryKey: ["site-preview", id],
    queryFn: () => api<Run>(`/site-previews/${id}`),
    enabled: !!id,
    refetchInterval: (query) =>
      query.state.data && terminal.has(query.state.data.status) ? false : 1000,
  });
  const operation = useQuery({
    queryKey: ["preview-operation", pendingId],
    queryFn: () => api<Run>(`/runs/${pendingId}`),
    enabled: !!pendingId,
    refetchInterval: (query) =>
      query.state.data && terminal.has(query.state.data.status) ? false : 700,
  });
  const run = preview.data;
  const frame = run?.metadata?.frame as Frame | undefined;
  const invalidate = () => {
    void cache.invalidateQueries({ queryKey: ["site-previews"] });
    void cache.invalidateQueries({ queryKey: ["site-preview"] });
  };
  const open = useMutation({
    mutationFn: () => {
      openReceipt.current ??= {
        client_request_id: randomId(),
        source_run_id: sourceRunId,
        artifact_id: artifactId,
        width: profile === "phone" ? 390 : 1240,
        height: profile === "phone" ? 844 : 800,
      };
      return post("/site-previews", openReceipt.current);
    },
    onError: (error) => {
      if (rejected(error)) openReceipt.current = null;
    },
    onSuccess: (value) => {
      openReceipt.current = null;
      actionReceipt.current = null;
      closeReceipt.current = null;
      action.reset();
      close.reset();
      setSelected(value.id);
      setPendingId(undefined);
      cache.setQueryData(["site-preview", value.id], value);
      invalidate();
    },
  });
  const action = useMutation({
    mutationFn: (value: Action | null) => {
      actionReceipt.current ??= {
        client_request_id: randomId(),
        expected_revision: frame!.revision,
        action: value,
      };
      return post(`/site-previews/${id}/actions`, actionReceipt.current);
    },
    onError: (error) => {
      if (rejected(error)) actionReceipt.current = null;
    },
    onSuccess: (value) => {
      actionReceipt.current = null;
      setPendingId(value.id);
      setText("");
      invalidate();
    },
  });
  const close = useMutation({
    mutationFn: () => {
      closeReceipt.current ??= { client_request_id: randomId() };
      return post(`/site-previews/${id}/close`, closeReceipt.current);
    },
    onError: (error) => {
      if (rejected(error)) closeReceipt.current = null;
    },
    onSuccess: (value) => {
      closeReceipt.current = null;
      setPendingId(value.id);
      invalidate();
    },
  });
  const operationStatus = operation.data?.status;
  useEffect(() => {
    if (operationStatus && terminal.has(operationStatus)) {
      void cache.invalidateQueries({ queryKey: ["site-preview"] });
    }
  }, [cache, operationStatus, pendingId]);
  const pending =
    !!pendingId &&
    (!operation.data ||
      !terminal.has(operation.data.status) ||
      (operation.data.status === "succeeded" &&
        operation.data.executor_type === "site_preview_action" &&
        typeof operation.data.metadata?.revision === "number" &&
        (frame?.revision ?? -1) < operation.data.metadata.revision));
  const ambiguous = action.isError && !rejected(action.error);
  const busy = open.isPending || action.isPending || close.isPending || pending;
  const closed =
    !!run?.metadata?.closed_at ||
    run?.status === "cancel_requested" ||
    run?.status === "canceled";
  const ready =
    run?.status === "running" &&
    !!frame &&
    !busy &&
    !ambiguous &&
    !close.isError &&
    frame.revision < 128;
  const active = run && !terminal.has(run.status);
  const needsCleanup =
    !!run?.metadata?.cleanup_requires_inspection && !run?.metadata?.closed_at;
  const canOpen =
    !active &&
    !needsCleanup &&
    !busy &&
    !!caps.data?.available &&
    !preview.isFetching &&
    !sessions.isLoading &&
    !!source.data &&
    !sessions.error;
  const status = closed
    ? "Closed"
    : pending
      ? "Applying interaction…"
      : run?.status === "running" && frame
        ? "Interactive · offline"
        : run?.status === "running" || run?.status === "preparing"
          ? "Opening page…"
          : run?.status === "queued"
            ? "Waiting for resources…"
            : run?.status === "succeeded"
              ? "Session ended"
              : run?.status === "interrupted"
                ? "Needs inspection"
                : run?.status === "failed"
                  ? "Could not open preview"
                  : "Ready to preview";
  const error =
    open.error ??
    action.error ??
    close.error ??
    preview.error ??
    operation.error ??
    source.error ??
    sessions.error ??
    caps.error;
  const click = (event: MouseEvent<HTMLButtonElement>) => {
    if (!ready || !frame || event.detail === 0) return;
    const bounds = event.currentTarget
      .querySelector("img")!
      .getBoundingClientRect();
    const x = Math.floor(
      ((event.clientX - bounds.left) * frame.width) / bounds.width,
    );
    const y = Math.floor(
      ((event.clientY - bounds.top) * frame.height) / bounds.height,
    );
    if (x >= 0 && x < frame.width && y >= 0 && y < frame.height)
      action.mutate({ kind: "click", x, y });
  };
  return (
    <section className="site-preview" aria-label="Website preview">
      <header className="site-preview-heading">
        <div>
          <Link
            className="text-link"
            to={
              source.data?.agent_id
                ? `/agents/${source.data.agent_id}?view=workspace`
                : source.data
                  ? `/coding/${source.data.task_id}`
                  : "/agents"
            }
          >
            ← Back to workspace
          </Link>
          <h1>Website preview</h1>
          <p className="muted">
            Explore this saved build. Your agent can keep working while you
            inspect it.
          </p>
        </div>
        <Button variant="secondary" asChild>
          <a
            href={`/api/artifacts/${artifactId}/file`}
            download="project-build.zip"
          >
            <ExternalLink size={15} /> Download build
          </a>
        </Button>
      </header>
      <div className="site-preview-bar">
        <span className="site-preview-status" role="status">
          <i className={ready ? "ready" : ""} />
          {status}
        </span>
        {!active && !needsCleanup ? (
          <div className="site-preview-start">
            <label>
              <span className="sr-only">Preview viewport</span>
              <select
                aria-label="Preview viewport"
                value={profile}
                onChange={(e) => setProfile(e.target.value)}
                disabled={busy || (open.isError && !rejected(open.error))}
              >
                <option value="desktop">Desktop · 1240 × 800</option>
                <option value="phone">Phone · 390 × 844</option>
              </select>
            </label>
            <Button disabled={!canOpen} onClick={() => open.mutate()}>
              <Play size={15} />
              {open.isError
                ? "Retry opening"
                : frame
                  ? "Open new session"
                  : "Open preview"}
            </Button>
          </div>
        ) : (
          <div className="site-preview-start">
            <span className="muted">
              {frame &&
                (frame.width < 600 ? (
                  <Smartphone size={16} />
                ) : (
                  <Monitor size={16} />
                ))}
              {frame && `${frame.width} × ${frame.height}`}
            </span>
            <Button
              variant="secondary"
              disabled={
                close.isPending ||
                (pending &&
                  operation.data?.executor_type === "site_preview_close")
              }
              onClick={() => close.mutate()}
            >
              <X size={15} />
              {close.isError ? "Retry closing" : "Close preview"}
            </Button>
          </div>
        )}
      </div>
      <p className="site-preview-notice">
        CPU only · No internet access · Saved build, not a live development
        server. Network features and external assets stay offline. Sessions last
        5 minutes.
      </p>
      {!caps.data?.available && caps.data && (
        <p className="muted">{caps.data.reason}</p>
      )}
      {error && (
        <div className="site-preview-error" role="alert">
          {error.message}
          {ambiguous && (
            <Button
              variant="secondary"
              onClick={() => action.mutate(null)}
              disabled={action.isPending}
            >
              Retry same interaction
            </Button>
          )}
        </div>
      )}
      {operation.data &&
        ["failed", "interrupted"].includes(operation.data.status) && (
          <p role="alert">
            {operation.data.error_message ||
              operation.data.summary ||
              "The interaction could not be completed. Inspect its run before retrying."}{" "}
            <Link to={`/runs/${operation.data.id}`} className="text-link">
              Inspect run
            </Link>
          </p>
        )}
      {run?.error_message && (
        <p role="alert">
          {run.error_message}{" "}
          <Link className="text-link" to={`/runs/${run.id}`}>
            Inspect run
          </Link>
        </p>
      )}
      {needsCleanup && (
        <p role="alert">
          Cleanup needs confirmation. Use Close preview to reconcile this
          session before opening another.
        </p>
      )}
      <div className="site-preview-stage">
        {frame ? (
          <button
            type="button"
            className="site-preview-screen"
            aria-label="Interactive website. Click a control, or use Tab and Enter to navigate the page."
            aria-disabled={!ready}
            onClick={click}
            onKeyDown={(event) => {
              if (
                ready &&
                keys.has(event.key) &&
                !event.ctrlKey &&
                !event.metaKey &&
                !event.altKey &&
                !event.shiftKey
              ) {
                event.preventDefault();
                action.mutate({
                  kind: "key",
                  key: event.key === " " ? "Space" : event.key,
                });
              }
            }}
          >
            <img
              src={`/api/artifacts/${frame.artifact_id}/file`}
              alt={
                frame.title
                  ? `Preview: ${frame.title}`
                  : "Saved website preview"
              }
              width={frame.width}
              height={frame.height}
              draggable={false}
            />
          </button>
        ) : (
          <div className="site-preview-empty">
            <Monitor size={40} />
            <h2>
              {active ? "Preparing your preview" : "See what your agent built"}
            </h2>
            <p>Open the build to try its buttons, forms and page layout.</p>
          </div>
        )}
      </div>
      {frame && (
        <>
          <div className="site-preview-controls">
            <div>
              <Button
                variant="secondary"
                disabled={!ready}
                onClick={() =>
                  action.mutate({ kind: "scroll", delta_x: 0, delta_y: -600 })
                }
                aria-label="Scroll website up"
              >
                <ArrowUp size={16} />
              </Button>
              <Button
                variant="secondary"
                disabled={!ready}
                onClick={() =>
                  action.mutate({ kind: "scroll", delta_x: 0, delta_y: 600 })
                }
                aria-label="Scroll website down"
              >
                <ArrowDown size={16} />
              </Button>
              <Button
                variant="secondary"
                disabled={!ready}
                onClick={() => action.mutate({ kind: "reset" })}
              >
                <RotateCcw size={15} /> Reset page
              </Button>
            </div>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                if (ready && text.trim()) action.mutate({ kind: "text", text });
              }}
            >
              <input
                aria-label="Text for focused website field"
                placeholder="Click a field above, then type here…"
                value={text}
                onChange={(event) => setText(event.target.value)}
                maxLength={2000}
                disabled={!ready}
              />
              <Button
                variant="secondary"
                disabled={!ready || !text.trim()}
                type="submit"
              >
                Type into page
              </Button>
            </form>
          </div>
          <p className="muted site-preview-footnote">
            {frame.path} · Frame {frame.revision + 1}
            {frame.blocked_requests > 0 &&
              ` · ${frame.blocked_requests} network requests blocked`}{" "}
            ·{" "}
            <Link className="text-link" to={`/runs/${id}`}>
              Execution details
            </Link>
          </p>
          {frame.revision >= 128 && (
            <p className="muted">
              This session reached its interaction limit. Close it and open a
              new session to continue.
            </p>
          )}
        </>
      )}
    </section>
  );
}
