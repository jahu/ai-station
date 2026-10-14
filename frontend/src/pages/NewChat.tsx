import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorNotice } from "../components/common";
import LlamaModels from "./LlamaModels";
import ConversationComposer from "./ConversationComposer";
import AssistantActions from "./AssistantActions";
import { emptyOptions } from "./assistant-options";
import TextAttachments, { type TextAttachment } from "./TextAttachments";
import { WebSearchControl } from "./ChatWebSearch";
import ChatModeSwitch, { type ChatMode } from "./ChatModeSwitch";
import type { ChatProviderInfo } from "./ChatProviders";

type Preferences = {
  version: number;
  mode: ChatMode;
  provider: string;
  model: string;
  send_key: "enter" | "ctrl-enter";
};
type Receipt = { conversation_id: string };

export default function NewChat({
  providers,
  provider,
  onProviderChange,
  onAccepted,
}: {
  providers: ChatProviderInfo[];
  provider?: ChatProviderInfo;
  onProviderChange: (key: string) => void;
  onAccepted: (id: string) => void;
}) {
  const cache = useQueryClient();
  const preferences = useQuery({
    queryKey: ["chat-preferences"],
    queryFn: () => api<Preferences>("/chat/preferences"),
  });
  const initialized = useRef(false);
  const pendingRequest = useRef<{ body: string; id: string } | null>(null);
  const [chosenMode, setMode] = useState<ChatMode | null>(null);
  const mode = chosenMode ?? preferences.data?.mode ?? "chat";
  const [selection, setSelection] = useState<{
    provider: string;
    model: string;
  } | null>(null);
  const [draft, setDraft] = useState("");
  const [options, setOptions] = useState(emptyOptions);
  const [attachments, setAttachments] = useState<TextAttachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const [modelPending, setModelPending] = useState(false);
  const [webEnabled, setWebEnabled] = useState(false);
  const [webQuery, setWebQuery] = useState("");
  useEffect(() => {
    if (initialized.current || !preferences.data || !providers.length) return;
    initialized.current = true;
    const saved = preferences.data;
    if (
      saved.model &&
      providers.some((p) => p.key === saved.provider && p.enabled)
    ) {
      onProviderChange(saved.provider);
    }
  }, [preferences.data, providers, onProviderChange]);
  const model =
    selection && selection.provider === provider?.key
      ? selection.model
      : preferences.data?.provider === provider?.key && preferences.data?.model
        ? preferences.data.model
        : provider?.default_model || provider?.models?.[0] || "";
  const send = useMutation({
    mutationFn: async () => {
      const values = {
        selection: { execution_mode: mode, provider: provider?.key, model },
        execution_mode: mode,
        content: draft.trim(),
        attachments,
        ...options,
        web_search: { enabled: webEnabled, query: webQuery },
      };
      const body = JSON.stringify(values);
      if (pendingRequest.current?.body !== body)
        pendingRequest.current = { body, id: crypto.randomUUID() };
      return api<Receipt>("/chat/turns", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...values,
          client_request_id: pendingRequest.current.id,
        }),
      });
    },
    onSuccess: (receipt) => {
      void cache.invalidateQueries({ queryKey: ["chat-preferences"] });
      void cache.invalidateQueries({ queryKey: ["conversations"] });
      onAccepted(receipt.conversation_id);
    },
  });
  const busy =
    send.isPending || uploading || modelPending || preferences.isPending;
  const canSend =
    !!draft.trim() &&
    !!model &&
    !!provider?.enabled &&
    (provider.secret_source === "none" || provider.secret_present) &&
    !busy &&
    (options.action !== "project.create_code" ||
      (!!options.new_project?.name.trim() &&
        (options.new_project.executor === "local" ||
          options.new_project.external_ai)));
  return (
    <section className="new-chat" aria-label="New conversation">
      <h1>What would you like to do?</h1>
      <p className="muted">
        {mode === "chat"
          ? "Ask, explore or create something."
          : "Describe your goal. Work with projects, code and agents."}
      </p>
      <div className="new-chat-controls">
        <ChatModeSwitch
          value={mode}
          disabled={send.isPending}
          onChange={(next) => {
            setMode(next);
            setOptions(emptyOptions);
          }}
        />
        {provider?.builtin ? (
          <LlamaModels
            selectionOnly
            compact
            value={model}
            models={provider.models ?? []}
            busy={send.isPending}
            onBusy={setModelPending}
            onSelect={(value) =>
              setSelection({ provider: provider.key, model: value })
            }
          />
        ) : (
          <label className="new-chat-model">
            Model
            <select
              value={model}
              onChange={(e) =>
                setSelection({
                  provider: provider?.key ?? "",
                  model: e.target.value,
                })
              }
            >
              {(provider?.models?.length
                ? provider.models
                : provider?.default_model
                  ? [provider.default_model]
                  : []
              ).map((name) => (
                <option key={name}>{name}</option>
              ))}
            </select>
          </label>
        )}
        {providers.length > 1 && (
          <label className="new-chat-provider">
            Provider
            <select
              aria-label="Provider"
              value={provider?.key ?? ""}
              onChange={(e) => {
                onProviderChange(e.target.value);
                const next = providers.find(
                  (item) => item.key === e.target.value,
                );
                setSelection({
                  provider: e.target.value,
                  model: next?.default_model || next?.models?.[0] || "",
                });
              }}
            >
              {providers.map((p) => (
                <option key={p.key} value={p.key} disabled={!p.enabled}>
                  {p.name} · {p.location}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      <ConversationComposer
        id="new-chat-message"
        value={draft}
        onChange={setDraft}
        onSend={() => send.mutate()}
        canSend={canSend}
        busy={busy}
        sendKey={preferences.data?.send_key}
        sendLabel="Send message"
        autoFocus
        placeholder={
          mode === "chat"
            ? "Ask a question or describe what to create…"
            : "What would you like to build or change?"
        }
        tools={
          <>
            <AssistantActions
              value={options}
              onChange={(value) => {
                setOptions(value);
                if (
                  ![
                    "auto",
                    "chat",
                    "image.generate",
                    "image.generate_video",
                  ].includes(value.action) ||
                  value.image_artifact_ids.length ||
                  value.audio_artifact_id
                )
                  setWebEnabled(false);
              }}
              allowWork={mode === "work"}
              busy={busy || attachments.length > 0}
              onUploading={setUploading}
            />
            {options.action !== "project.create_code" &&
              !options.image_artifact_ids.length &&
              !options.audio_artifact_id && (
                <TextAttachments
                  attachments={attachments}
                  onChange={setAttachments}
                  busy={send.isPending}
                  onReading={setUploading}
                />
              )}
          </>
        }
        controls={
          <>
            {[
              "auto",
              "chat",
              "image.generate",
              "image.generate_video",
            ].includes(options.action) &&
              !options.image_artifact_ids.length &&
              !options.audio_artifact_id && (
                <WebSearchControl
                  compact
                  enabled={webEnabled}
                  query={webQuery}
                  busy={busy}
                  onToggle={setWebEnabled}
                  onQuery={setWebQuery}
                />
              )}
          </>
        }
      />
      {provider?.location === "external" && (
        <p className="notice">
          External AI · Your message and selected attachments will be sent to{" "}
          {provider.name}.
        </p>
      )}
      {!model && (
        <p className="muted">Choose an available model to send your message.</p>
      )}
      <ErrorNotice error={send.error ?? preferences.error} />
    </section>
  );
}
