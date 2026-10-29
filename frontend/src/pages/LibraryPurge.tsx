import { useEffect, useMemo, useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { LoaderCircle, Trash2, X } from "lucide-react";
import { api, type Artifact, type Run } from "../api";
import { randomId } from "../lib/random-id";
import { ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";

type Item = { id: string; name: string; version: string | null };
type Outcome = {
  state: "deleted" | "failed";
  error?: string;
  retained_shared_paths?: string[];
};
type PurgeRun = Run & {
  parameters: Run["parameters"] & { items: Item[]; scope: string };
  metadata: Run["metadata"] & {
    purge_outcomes?: Record<string, Outcome>;
    purge_progress_dismissed_at?: string;
  };
};
const terminal = new Set(["succeeded", "failed", "canceled", "interrupted"]);
const keys = [
  "library",
  "library-purges",
  "library-trash-count",
  "artifacts",
  "artifact",
  "artifact-lineage",
  "media-result",
  "media-inputs",
  "dashboard",
];

export function PurgeButton({
  artifacts = [],
  emptyTrash = false,
  count,
  compact = false,
  tabIndex,
  onConfirmed,
  existingRun,
}: {
  artifacts?: Artifact[];
  emptyTrash?: boolean;
  count?: number;
  compact?: boolean;
  tabIndex?: number;
  onConfirmed?: () => void;
  existingRun?: PurgeRun;
}) {
  const cache = useQueryClient();
  const [open, setOpen] = useState(false);
  const [prepared, setPrepared] = useState<PurgeRun | null>(null);
  const requestId = useRef("");
  const prepare = useMutation({
    mutationFn: () => {
      requestId.current ||= randomId();
      return api<PurgeRun>("/library/purges", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          request_id: requestId.current,
          scope: emptyTrash ? "trash" : "selected",
          items: emptyTrash
            ? []
            : artifacts.map((a) => ({
                id: a.id,
                expected_updated_at: a.library_updated_at ?? null,
              })),
        }),
      });
    },
    onSuccess: (run) => {
      setPrepared(run);
      void cache.invalidateQueries({ queryKey: ["library-purges"] });
    },
  });
  const resolve = useMutation({
    mutationFn: async (resolution: "granted" | "denied") => {
      try {
        return await api<PurgeRun>(`/runs/${prepared!.id}/approval`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ resolution }),
        });
      } catch (error) {
        // A lost response must not strand an already resolved confirmation.
        const current = await api<PurgeRun>(`/runs/${prepared!.id}`).catch(
          () => null,
        );
        if (current?.approval?.resolution === resolution) return current;
        throw error;
      }
    },
    onSuccess: (_, resolution) => {
      setOpen(false);
      setPrepared(null);
      requestId.current = "";
      keys.forEach((key) => void cache.invalidateQueries({ queryKey: [key] }));
      if (resolution === "granted") onConfirmed?.();
    },
  });
  const items = prepared?.parameters.items ?? [];
  const label = existingRun
    ? "Review deletion"
    : emptyTrash
      ? `Empty Trash${count === undefined ? "" : ` (${count})`}`
      : artifacts.length > 1
        ? `Delete selected permanently (${artifacts.length})`
        : "Delete permanently";
  return (
    <>
      <Button
        variant="ghost"
        className="library-purge-trigger"
        tabIndex={tabIndex}
        aria-label={
          compact ? `Delete permanently ${artifacts[0]?.id.slice(0, 8)}` : label
        }
        title={label}
        disabled={existingRun ? false : emptyTrash ? !count : !artifacts.length}
        onClick={() => {
          setOpen(true);
          prepare.reset();
          resolve.reset();
          if (existingRun) setPrepared(existingRun);
          else prepare.mutate();
        }}
      >
        <Trash2 size={15} />
        {!compact && label}
      </Button>
      <Dialog.Root
        open={open}
        onOpenChange={(next) => {
          if (next || prepare.isPending || resolve.isPending) return;
          if (prepared) resolve.mutate("denied");
          else {
            setOpen(false);
            requestId.current = "";
          }
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content
            className="library-dialog library-purge-dialog"
            aria-describedby="purge-explanation"
          >
            <Dialog.Title>Delete permanently?</Dialog.Title>
            <Dialog.Description id="purge-explanation">
              Files are removed from storage and cannot be restored. Execution
              history and source references stay available.
            </Dialog.Description>
            {prepare.isPending && (
              <p role="status">
                <LoaderCircle size={16} className="spin" /> Preparing the exact
                selection…
              </p>
            )}
            {prepared && (
              <>
                <p>
                  <strong>
                    {items.length} artifact{items.length === 1 ? "" : "s"}
                  </strong>
                  {emptyTrash
                    ? " in the complete Trash, across every page and filter."
                    : " in this confirmed selection."}
                </p>
                <ul className="library-purge-items">
                  {items.map((item) => (
                    <li key={item.id}>
                      {item.name}
                      <small>{item.id.slice(0, 8)}</small>
                    </li>
                  ))}
                </ul>
                <p className="muted">
                  Newly trashed files will not be added. If an item changes
                  before deletion, it is skipped and reported.
                </p>
              </>
            )}
            <ErrorNotice error={prepare.error ?? resolve.error} />
            <div className="dialog-actions">
              <Button
                variant="secondary"
                disabled={prepare.isPending || resolve.isPending}
                onClick={() => {
                  if (prepared) resolve.mutate("denied");
                  else {
                    setOpen(false);
                    requestId.current = "";
                  }
                }}
              >
                Keep files
              </Button>
              {prepare.isError && (
                <Button variant="secondary" onClick={() => prepare.mutate()}>
                  Retry preparing
                </Button>
              )}
              <Button
                className="library-trash-confirm"
                disabled={
                  !prepared ||
                  resolve.isPending ||
                  prepared.status !== "waiting_for_approval"
                }
                onClick={() => resolve.mutate("granted")}
              >
                {resolve.isPending ? "Saving…" : "Delete permanently"}
              </Button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}

export function PurgeActivity({ artifactId }: { artifactId?: string } = {}) {
  const cache = useQueryClient();
  const previous = useRef<Record<string, string>>({});
  const [dismissed, setDismissed] = useState<string[]>([]);
  const query = useQuery({
    queryKey: ["library-purges"],
    queryFn: () => api<PurgeRun[]>("/library/purges"),
    refetchInterval: (state) =>
      Array.isArray(state.state.data) &&
      state.state.data.some((run) => !terminal.has(run.status))
        ? 1000
        : 10000,
  });
  const rows = useMemo(
    () =>
      Array.isArray(query.data)
        ? query.data.filter(
            (run) =>
              Array.isArray(run.parameters?.items) &&
              (!artifactId ||
                run.parameters.items.some((item) => item.id === artifactId)),
          )
        : [],
    [query.data, artifactId],
  );
  useEffect(() => {
    let changed = false;
    for (const run of rows) {
      const outcomes = Object.values(run.metadata?.purge_outcomes ?? {});
      const version = `${run.status}:${outcomes.length}:${outcomes.filter((item) => item.state === "failed").length}`;
      if (previous.current[run.id] !== version) changed = true;
      previous.current[run.id] = version;
    }
    if (changed)
      keys
        .filter((key) => key !== "library-purges")
        .forEach((key) => void cache.invalidateQueries({ queryKey: [key] }));
  }, [rows, cache]);
  const cancel = useMutation({
    mutationFn: (id: string) => api(`/runs/${id}/cancel`, { method: "POST" }),
    onSuccess: () => cache.invalidateQueries({ queryKey: ["library-purges"] }),
  });
  const dismiss = useMutation({
    mutationFn: (id: string) =>
      api<PurgeRun>(`/library/purges/${id}/dismiss`, { method: "POST" }),
    onMutate: (id) => setDismissed((old) => [...old, id]),
    onError: (_, id) =>
      setDismissed((old) => old.filter((item) => item !== id)),
    onSuccess: (updated) => {
      cache.setQueryData<PurgeRun[]>(["library-purges"], (old) =>
        old?.map((item) => (item.id === updated.id ? updated : item)),
      );
    },
    onSettled: () => cache.invalidateQueries({ queryKey: ["library-purges"] }),
  });
  const recentFinished = rows
    .filter(
      (run) =>
        terminal.has(run.status) &&
        !(
          run.status === "canceled" &&
          !Object.keys(run.metadata?.purge_outcomes ?? {}).length
        ),
    )
    .slice(0, 3);
  const progressRows = [
    ...rows.filter((run) => !terminal.has(run.status)),
    ...recentFinished,
  ];
  return (
    <>
      <ErrorNotice error={query.error ?? cancel.error ?? dismiss.error} />
      {progressRows
        // Closing a card must not immediately fill its slot with an older,
        // indistinguishable completion. Keep the same recent window on refresh.
        .filter(
          (run) =>
            !terminal.has(run.status) ||
            (!dismissed.includes(run.id) &&
              !run.metadata?.purge_progress_dismissed_at),
        )
        .map((run) => {
          const outcomes = run.metadata?.purge_outcomes ?? {};
          const deleted = Object.values(outcomes).filter(
            (item) => item.state === "deleted",
          ).length;
          const failed = Object.values(outcomes).filter(
            (item) => item.state === "failed",
          ).length;
          const remaining = run.parameters.items.filter(
            (item) => outcomes[item.id]?.state !== "deleted",
          );
          const active = !terminal.has(run.status);
          return (
            <section
              className="panel library-purge-progress"
              key={run.id}
              aria-label="Permanent deletion progress"
            >
              <div className="library-purge-progress-header">
                <strong>
                  {run.status === "waiting_for_approval"
                    ? "Deletion awaiting confirmation"
                    : active
                      ? "Deleting artifacts"
                      : run.status === "succeeded"
                        ? "Permanent deletion complete"
                        : "Permanent deletion stopped"}
                </strong>
                {active ? (
                  <Button
                    variant="secondary"
                    disabled={
                      cancel.isPending || run.status === "cancel_requested"
                    }
                    onClick={() => cancel.mutate(run.id)}
                  >
                    {run.status === "cancel_requested" ? "Stopping…" : "Stop"}
                  </Button>
                ) : (
                  <Button
                    variant="ghost"
                    aria-label="Dismiss deletion progress"
                    onClick={() => dismiss.mutate(run.id)}
                  >
                    <X size={16} />
                  </Button>
                )}
              </div>
              {run.status === "waiting_for_approval" && (
                <PurgeButton existingRun={run} />
              )}
              <progress
                value={Object.keys(outcomes).length}
                max={run.parameters.items.length}
                aria-label="Artifacts processed"
              />
              <p role="status">
                {deleted} of {run.parameters.items.length} deleted
                {failed ? ` · ${failed} failed` : ""}
                {!active && remaining.length
                  ? ` · ${remaining.length} remain`
                  : ""}
              </p>
              <Link to={`/runs/${run.id}`}>Inspect execution history</Link>
              {failed > 0 && (
                <details>
                  <summary>Files that could not be deleted</summary>
                  <ul>
                    {run.parameters.items
                      .filter((item) => outcomes[item.id]?.state === "failed")
                      .map((item) => (
                        <li key={item.id}>
                          {item.name}: {outcomes[item.id].error}
                        </li>
                      ))}
                  </ul>
                </details>
              )}
              {!active && remaining.length > 0 && (
                <PurgeRetry ids={remaining.map((item) => item.id)} />
              )}
            </section>
          );
        })}
    </>
  );
}

function PurgeRetry({ ids }: { ids: string[] }) {
  const [items, setItems] = useState<Artifact[]>([]);
  const load = useMutation({
    mutationFn: () =>
      Promise.all(ids.map((id) => api<Artifact>(`/artifacts/${id}`))),
    onSuccess: (rows) => setItems(rows.filter((row) => !row.purged_at)),
  });
  return (
    <div className="library-purge-retry">
      <ErrorNotice error={load.error} />
      {items.length ? (
        <PurgeButton artifacts={items} />
      ) : (
        <Button
          variant="secondary"
          disabled={load.isPending}
          onClick={() => load.mutate()}
        >
          {load.isPending
            ? "Checking remaining files…"
            : "Review remaining files"}
        </Button>
      )}
    </div>
  );
}
