import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";
import { Brain, X } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";
import UnifiedModelPicker from "./UnifiedModelPicker";

type Settings = {
  use: boolean;
  learn: boolean;
  revision: number;
  local_provider?: string;
  local_model?: string;
  recent_runs: {
    id: string;
    status: string;
    summary: string;
    capability: string;
    task_id: string;
  }[];
};
type Props = {
  compact?: boolean;
  conversationId?: string;
  enabled?: boolean;
  autoSummary?: boolean;
  busy?: boolean;
};
const active = new Set([
  "queued",
  "claimed",
  "preparing",
  "running",
  "waiting_for_tool",
  "cancel_requested",
]);
const json = (body: unknown) => ({
  method: "PUT",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export default function PersonalMemory({
  compact,
  conversationId,
  enabled = true,
  autoSummary = false,
  busy = false,
}: Props) {
  const cache = useQueryClient();
  const settings = useQuery({
    queryKey: ["personal-memory-settings"],
    queryFn: () => api<Settings>("/memory/personal/settings"),
    refetchInterval: 5000,
  });
  const refresh = () => {
    void cache.invalidateQueries({ queryKey: ["personal-memory-settings"] });
    void cache.invalidateQueries({ queryKey: ["memory"] });
    if (conversationId)
      void cache.invalidateQueries({
        queryKey: ["conversation", conversationId],
      });
  };
  const change = useMutation({
    mutationFn: (values: {
      use: boolean;
      learn: boolean;
      local_provider?: string;
      local_model?: string;
    }) =>
      api<Settings>(
        "/memory/personal/settings",
        json({ ...values, expected_revision: settings.data!.revision }),
      ),
    onSuccess: (data) => {
      cache.setQueryData(["personal-memory-settings"], data);
      refresh();
    },
  });
  const perChat = useMutation({
    mutationFn: (value: boolean) =>
      api(`/chat/conversations/${conversationId}/context`, {
        ...json({ auto_summary: autoSummary, personal_memory: value }),
        method: "PATCH",
      }),
    onSuccess: refresh,
  });
  const history = useMutation({
    mutationFn: () => api("/memory/personal/history", { method: "POST" }),
    onSuccess: refresh,
  });
  const stop = useMutation({
    mutationFn: (id: string) =>
      api(`/memory/personal/runs/${id}/cancel`, { method: "POST" }),
    onSuccess: refresh,
  });
  const data = settings.data;
  const state = !data
    ? "…"
    : !data.use || !enabled
      ? "off"
      : data.learn
        ? "on"
        : "saved only";
  const content = (
    <div className="personal-memory-body">
      <p className="muted">
        Let AI Station remember useful details between conversations — your
        name, preferences and lasting decisions. Personal memories stay private
        to your account.
      </p>
      <ErrorNotice
        error={
          settings.error ??
          change.error ??
          perChat.error ??
          history.error ??
          stop.error
        }
      />
      {!data ? (
        <p>Loading memory settings…</p>
      ) : (
        <>
          <label className="personal-memory-choice">
            <input
              type="checkbox"
              checked={data.use}
              disabled={change.isPending}
              onChange={(event) =>
                change.mutate({ use: event.target.checked, learn: data.learn })
              }
            />
            <span>
              <strong>Use saved memories</strong>
              <small>Bring relevant context into new conversations.</small>
            </span>
          </label>
          <label className="personal-memory-choice">
            <input
              type="checkbox"
              checked={data.learn}
              disabled={change.isPending || !data.use}
              onChange={(event) =>
                change.mutate({ use: data.use, learn: event.target.checked })
              }
            />
            <span>
              <strong>Learn from conversations</strong>
              <small>
                Use your local model to save and update useful details after
                successful replies. Off by default.
              </small>
            </span>
          </label>
          {conversationId && (
            <label className="personal-memory-choice">
              <input
                type="checkbox"
                checked={enabled}
                disabled={busy || perChat.isPending}
                onChange={(event) => perChat.mutate(event.target.checked)}
              />
              <span>
                <strong>Allow memory in this conversation</strong>
                <small>
                  Turning this off stops personal recall and learning here. Chat
                  history is still saved.
                </small>
              </span>
            </label>
          )}
          <p className="muted">
            You can inspect, correct, disable or forget any memory. Manual
            corrections are protected from automatic changes. Learning uses a
            local model; it does not silently send conversations to a cloud
            provider.
          </p>
          {!compact && (
            <details>
              <summary>Local learning model</summary>
              <p className="muted">
                By default, learning reuses the conversation’s local model.
                Choose a fixed local model to also learn from chats with an
                external provider. No external model is used for extraction.
              </p>
              <UnifiedModelPicker
                allowedLocation="local"
                providerKey={data.local_provider ?? ""}
                modelKey={data.local_model ?? ""}
                label={
                  data.local_model
                    ? undefined
                    : "Use conversation’s local model"
                }
                busy={change.isPending}
                onSelect={(choice) =>
                  change.mutate({
                    use: data.use,
                    learn: data.learn,
                    local_provider: choice.provider_key,
                    local_model: choice.model_key,
                  })
                }
              />
              {!!data.local_model && (
                <Button
                  variant="ghost"
                  type="button"
                  onClick={() =>
                    change.mutate({
                      use: data.use,
                      learn: data.learn,
                      local_provider: "",
                      local_model: "",
                    })
                  }
                >
                  Use conversation’s local model
                </Button>
              )}
            </details>
          )}
          {!compact && (
            <div className="row">
              <Button
                type="button"
                variant="secondary"
                disabled={
                  !data.use ||
                  !data.learn ||
                  history.isPending ||
                  data.recent_runs?.some(
                    (run) =>
                      run.capability === "memory.personal.history" &&
                      active.has(run.status),
                  )
                }
                onClick={() => history.mutate()}
              >
                Learn from earlier chats
              </Button>
              <small className="muted">
                Optional: review up to 20 unprocessed turns per batch.
              </small>
            </div>
          )}
          {data.recent_runs?.length > 0 && (
            <details className="personal-memory-activity">
              <summary>
                Memory activity{" "}
                {data.recent_runs.some((run) => active.has(run.status))
                  ? "· working"
                  : ""}
              </summary>
              {data.recent_runs.slice(0, 5).map((run) => (
                <div className="row" key={run.id}>
                  <Link to={`/runs/${run.id}`}>
                    {run.capability.endsWith("capture")
                      ? "Learn"
                      : run.capability.endsWith("recall")
                        ? "Recall"
                        : "Earlier chats"}{" "}
                    · {run.status}
                  </Link>
                  {active.has(run.status) && (
                    <Button
                      type="button"
                      variant="ghost"
                      disabled={stop.isPending}
                      onClick={() => stop.mutate(run.id)}
                    >
                      Stop
                    </Button>
                  )}
                  {run.summary && (
                    <small className="muted">{run.summary}</small>
                  )}
                </div>
              ))}
            </details>
          )}
          {compact && <Link to="/memory">Review and manage memories →</Link>}
        </>
      )}
    </div>
  );
  if (!compact)
    return (
      <section
        className="panel personal-memory-panel"
        aria-label="Personal memory"
      >
        <h2>
          <Brain size={18} aria-hidden="true" /> Personal memory
        </h2>
        {content}
      </section>
    );
  return (
    <Dialog.Root>
      <Dialog.Trigger asChild>
        <Button
          type="button"
          variant="ghost"
          className="personal-memory-trigger"
          aria-label={`Personal memory: ${state}`}
        >
          <Brain size={16} aria-hidden="true" />
          <span>Memory · {state}</span>
        </Button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="chat-options-dialog personal-memory-dialog">
          <div className="row">
            <Dialog.Title>Personal memory</Dialog.Title>
            <Dialog.Close asChild>
              <Button
                type="button"
                variant="ghost"
                aria-label="Close memory settings"
              >
                <X size={18} />
              </Button>
            </Dialog.Close>
          </div>
          <Dialog.Description className="muted">
            Your context, across conversations. You choose what AI Station
            remembers.
          </Dialog.Description>
          {content}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export type MemoryRecall = {
  method: string;
  run_id: string;
  sources: { id: string; content: string }[];
};
export function MemorySources({ value }: { value?: MemoryRecall }) {
  if (!value) return null;
  return (
    <details className="personal-memory-sources">
      <summary>
        <Brain size={13} aria-hidden="true" />{" "}
        {value.sources.length
          ? `Used ${value.sources.length} saved ${value.sources.length === 1 ? "memory" : "memories"}`
          : "Memory checked"}
      </summary>
      <ul>
        {value.sources.map((source) => (
          <li key={source.id}>
            <Link to={`/memory/${source.id}`}>{source.content}</Link>
          </li>
        ))}
      </ul>
      <small className="muted">
        {value.method} ·{" "}
        <Link to={`/runs/${value.run_id}`}>Inspect recall</Link>
      </small>
    </details>
  );
}
