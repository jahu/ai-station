import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, Paperclip } from "lucide-react";
import { api } from "../api";
import { Button } from "../components/ui/button";
import { ErrorNotice } from "../components/common";
import LlamaModels from "./LlamaModels";
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
  const [mode, setMode] = useState<ChatMode>("chat");
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
    if (saved.mode === "chat" || saved.mode === "work") setMode(saved.mode);
    if (
      saved.model &&
      providers.some((p) => p.key === saved.provider && p.enabled)
    ) {
      onProviderChange(saved.provider);
      setSelection({ provider: saved.provider, model: saved.model });
    }
  }, [preferences.data, providers, onProviderChange]);
  const model =
    selection && selection.provider === provider?.key
      ? selection.model
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
  const busy = send.isPending || uploading || modelPending;
  const canSend =
    !!draft.trim() &&
    !!model &&
    !!provider?.enabled &&
    (provider.secret_source === "none" || provider.secret_present) &&
    !busy;
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
                setSelection(null);
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
      <form
        className="new-chat-composer"
        onSubmit={(e) => {
          e.preventDefault();
          if (canSend) send.mutate();
        }}
      >
        <label className="sr-only" htmlFor="new-chat-message">
          Message
        </label>
        <textarea
          id="new-chat-message"
          autoFocus
          rows={4}
          maxLength={32000}
          value={draft}
          placeholder={
            mode === "chat"
              ? "Ask a question or describe what to create…"
              : "What would you like to build or change?"
          }
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key !== "Enter" || e.nativeEvent.isComposing || e.shiftKey)
              return;
            const shortcut = e.ctrlKey || e.metaKey;
            if (
              preferences.data?.send_key === "ctrl-enter" ? !shortcut : e.altKey
            )
              return;
            e.preventDefault();
            if (canSend) send.mutate();
          }}
        />
        <details className="new-chat-tools">
          <summary>
            <Paperclip size={15} /> Attach files &amp; choose tools
          </summary>
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
          {!options.image_artifact_ids.length && !options.audio_artifact_id && (
            <TextAttachments
              attachments={attachments}
              onChange={setAttachments}
              busy={send.isPending}
              onReading={setUploading}
            />
          )}
        </details>
        <div className="new-chat-footer">
          {["auto", "chat", "image.generate", "image.generate_video"].includes(
            options.action,
          ) &&
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
          <Button type="submit" aria-label="Send message" disabled={!canSend}>
            <ArrowUp size={18} />
            {send.isPending ? "Sending…" : "Send"}
          </Button>
        </div>
      </form>
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
