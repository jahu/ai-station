import { useId, type KeyboardEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api";
import { ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";
import { time } from "../lib/utils";
import { useListKeyboard } from "./useListKeyboard";

export interface Summary {
  id: string;
  run_id: string;
  memory_id: string | null;
  enabled: boolean;
  content: string;
  source_message_ids: string[];
  previous_summary_id: string | null;
  created_at: string;
  covered_offset?: number;
  covered_message_length?: number;
}
function AutoSummaryChoiceList({
  checked,
  disabled,
  onChange,
}: {
  checked: boolean;
  disabled: boolean;
  onChange: (enabled: boolean) => void;
}) {
  const labelId = useId();
  const items = ["auto_summary"] as const;
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    [...items],
    (item) => item,
  );
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown(event);
    if (event.defaultPrevented) return;
    if (event.key !== " " && event.key !== "Enter") return;
    const target = event.target as HTMLElement;
    if (target.closest("a, button, textarea, input, summary, select")) return;
    if (disabled) return;
    event.preventDefault();
    onChange(!checked);
  };
  return (
    <>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose automatic memory while the list is focused. Space or
        Enter selects it. Each update is a visible, cancelable Run. There is no
        inspectable summary-policy Run.
      </p>
      <div
        ref={listRef}
        className="summary-choice-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        <div
          aria-label="Summary auto_summary"
          {...itemProps(0, "auto_summary")}
        >
          <label className="project-checkbox">
            <input
              type="checkbox"
              checked={checked}
              disabled={disabled}
              tabIndex={index === 0 ? 0 : -1}
              onChange={(event) => onChange(event.target.checked)}
            />
            Automatically maintain conversation memory
          </label>
        </div>
      </div>
    </>
  );
}

export default function ConversationSummary({
  conversationId,
  summary,
  busy,
  autoSummary = false,
  lastUpdate,
}: {
  conversationId: string;
  summary: Summary | null;
  busy: boolean;
  autoSummary?: boolean;
  lastUpdate?: { id: string; status: string; error_message: string } | null;
}) {
  const cache = useQueryClient();
  const policy = useMutation({
    mutationFn: (enabled: boolean) =>
      api(`/chat/conversations/${conversationId}/context`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ auto_summary: enabled }),
      }),
    onSuccess: () => {
      void cache.invalidateQueries({
        queryKey: ["conversation", conversationId],
      });
    },
  });
  const update = useMutation({
    mutationFn: () =>
      api(`/chat/conversations/${conversationId}/summarize`, {
        method: "POST",
      }),
    onSuccess: () => {
      void cache.invalidateQueries({
        queryKey: ["conversation", conversationId],
      });
    },
  });
  return (
    <details className="chat-settings-panel">
      <summary>
        Conversation memory ·{" "}
        {autoSummary
          ? "Automatic updates on"
          : summary?.enabled
            ? "Summary active"
            : "Recent messages only"}
      </summary>
      <div className="content-panel">
        <p className="muted">
          Update the summary of older messages using your local model. The
          newest eight stay verbatim; full history is preserved. A message
          longer than the 48,000-character segment is summarized in labeled
          chunks across later updates.
        </p>
        <AutoSummaryChoiceList
          checked={autoSummary}
          disabled={busy || policy.isPending}
          onChange={(enabled) => policy.mutate(enabled)}
        />
        <p className="muted">
          After successful replies, your local model summarizes older context
          when 16 messages or 40,000 characters accumulate. Each update is a
          visible, cancelable Run. Disabled or deleted memory is not recreated
          automatically.
        </p>
        <Button
          variant="secondary"
          disabled={busy || update.isPending}
          onClick={() => update.mutate()}
        >
          {update.isPending ? "Queueing…" : "Update summary"}
        </Button>
        <ErrorNotice error={policy.error ?? update.error} />
        {lastUpdate &&
          ["failed", "canceled", "interrupted"].includes(lastUpdate.status) && (
            <p className="notice">
              Last memory update {lastUpdate.status}. Earlier memory and
              messages are preserved.{" "}
              <Link to={`/runs/${lastUpdate.id}`}>Inspect update →</Link>
            </p>
          )}
        {summary ? (
          <>
            <p className="muted">
              {time(summary.created_at)} · {summary.source_message_ids.length}{" "}
              source messages in this update
              {summary.previous_summary_id && " · Builds on an earlier summary"}
              {summary.covered_offset
                ? ` · Partial coverage through character ${summary.covered_offset} of ${summary.covered_message_length ?? "an oversized message"}; the remainder waits for a later update`
                : ""}
            </p>
            {summary.enabled ? (
              <pre className="summary-content">{summary.content}</pre>
            ) : (
              <p className="notice">
                Summary memory is disabled or deleted. It will not enter new
                requests.
              </p>
            )}
            <div className="row">
              <Link to={`/runs/${summary.run_id}`}>
                Inspect summary Run and sources
              </Link>
              {summary.memory_id && (
                <Link to={`/memory/${summary.memory_id}`}>
                  Edit or disable memory
                </Link>
              )}
            </div>
          </>
        ) : (
          <p className="muted">
            No summary yet. Requests use up to 16 recent messages and any pinned
            context. More than eight eligible messages are needed to summarize.
          </p>
        )}
      </div>
    </details>
  );
}
