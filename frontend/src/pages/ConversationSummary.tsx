import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api";
import { ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";
import { time } from "../lib/utils";

export interface Summary {
  id: string;
  run_id: string;
  memory_id: string | null;
  enabled: boolean;
  content: string;
  source_message_ids: string[];
  previous_summary_id: string | null;
  created_at: string;
}
export default function ConversationSummary({
  conversationId,
  summary,
  busy,
}: {
  conversationId: string;
  summary: Summary | null;
  busy: boolean;
}) {
  const cache = useQueryClient();
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
        {summary?.enabled ? "Summary active" : "Recent messages only"}
      </summary>
      <div className="content-panel">
        <p className="muted">
          Update the summary of older messages using your local model. The
          newest eight stay verbatim; full history is preserved. Updates run
          only when requested.
        </p>
        <Button
          variant="secondary"
          disabled={busy || update.isPending}
          onClick={() => update.mutate()}
        >
          {update.isPending ? "Queueing…" : "Update summary"}
        </Button>
        <ErrorNotice error={update.error} />
        {summary ? (
          <>
            <p className="muted">
              {time(summary.created_at)} · {summary.source_message_ids.length}{" "}
              source messages in this update
              {summary.previous_summary_id && " · Builds on an earlier summary"}
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
