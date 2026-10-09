import {
  WebSearchControl,
  SearchSources,
  type WebSources,
} from "./ChatWebSearch";
import LlamaModels from "./LlamaModels";
import { emptyOptions } from "./assistant-options";
import AssistantActions, {
  AssistantResults,
  type ActionResult,
} from "./AssistantActions";
import TextAttachments, { type TextAttachment } from "./TextAttachments";
import ConversationSummary, { type Summary } from "./ConversationSummary";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { Copy, MessageSquare, Plus, Send, Square } from "lucide-react";
import { api, type Run } from "../api";
import {
  Badge,
  Empty,
  ErrorNotice,
  Loading,
  PageTitle,
} from "../components/common";
import { Button } from "../components/ui/button";
import { time } from "../lib/utils";

type Conversation = {
  id: string;
  execution_mode?: "local" | "orchestrator";
  title: string;
  model: string;
  model_label?: string;
  system_prompt: string;
  temperature: number;
  max_tokens: number;
  updated_at: string;
};
type Message = ActionResult & {
  id: string;
  role: string;
  content: string;
  created_at: string;
  run_id: string | null;
  run_status: string | null;
  error_message: string;
  metadata: {
    web_search?: WebSources;
    orchestration?: boolean;
    routing_only?: boolean;
    agent_id?: string;
    images?: { id: string; name: string }[];
    partial?: boolean;
    superseded?: boolean;
    user_text?: string;
    attachments?: {
      id: string;
      name: string;
      size_bytes: number;
      kind?: string;
      pixels_sent?: boolean;
      extracted_text?: boolean;
      extracted_chars?: number;
    }[];
  };
};
type Detail = Conversation & {
  auto_summary: boolean;
  summary_update: { id: string; status: string; error_message: string } | null;
  messages: Message[];
  active_run: Run | null;
  summary: Summary | null;
};
type Provider = {
  id: string;
  name: string;
  location: string;
  endpoint: string;
  models: string[];
  default_model: string;
  status: string;
  error: string | null;
};
const json = (body: unknown) => ({
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export default function Chat({ assistant = false }: { assistant?: boolean }) {
  const { id } = useParams();
  const cache = useQueryClient();
  const navigate = useNavigate();
  const conversations = useQuery({
    queryKey: ["conversations"],
    queryFn: () => api<Conversation[]>("/chat/conversations"),
    refetchInterval: 5000,
  });
  const provider = useQuery({
    queryKey: ["chat-provider"],
    queryFn: () => api<Provider>("/chat/provider"),
    retry: false,
  });
  const detail = useQuery({
    queryKey: ["conversation", id],
    queryFn: () => api<Detail>(`/chat/conversations/${id}`),
    enabled: !!id,
    refetchInterval: 2000,
  });
  const active = detail.data?.active_run;
  useEffect(() => {
    if (!active?.id) return;
    const source = new EventSource(`/api/runs/${active.id}/stream`);
    const refresh = () => {
      void cache.invalidateQueries({ queryKey: ["conversation", id] });
    };
    source.onmessage = refresh;
    source.addEventListener("end", () => {
      refresh();
      source.close();
      void cache.invalidateQueries({ queryKey: ["conversations"] });
    });
    return () => source.close();
  }, [active?.id, id, cache]);
  const create = useMutation({
    mutationFn: (body: unknown) =>
      api<Conversation>("/chat/conversations", {
        method: "POST",
        ...json(body),
      }),
    onSuccess: (row) => {
      void cache.invalidateQueries({ queryKey: ["conversations"] });
      navigate(`/chat/${row.id}`);
    },
  });
  return (
    <>
      <PageTitle
        eyebrow="WORKSPACE / CHAT"
        title={assistant ? "What shall we create?" : "Think it through."}
      >
        {assistant
          ? "One conversation for your workstation. Create images, prepare agents, code in projects and inspect the results here."
          : "Persistent conversations with your configured local model. Every response has a Run."}
      </PageTitle>
      <ErrorNotice
        error={
          conversations.error ??
          provider.error ??
          (id ? detail.error : null) ??
          create.error
        }
      />
      <div className="chat-layout">
        <aside className="panel chat-history">
          <Button asChild>
            <Link to={assistant ? "/" : "/chat"}>
              <Plus size={15} />
              New conversation
            </Link>
          </Button>
          {conversations.data?.map((row) => (
            <Link
              className={id === row.id ? "selected" : ""}
              key={row.id}
              to={`/chat/${row.id}`}
            >
              <MessageSquare size={15} />
              <span>
                <strong>{row.title}</strong>
                <small>
                  {row.model_label ?? row.model} · {time(row.updated_at)}
                </small>
              </span>
            </Link>
          ))}
          {!conversations.isPending && !conversations.data?.length && (
            <p className="muted">
              Your conversations will stay here after a restart.
            </p>
          )}
        </aside>
        <section className="chat-main panel">
          {!id ? (
            <div className="content-panel">
              <h2>Start a conversation</h2>
              <p className="muted">
                Choose Platform assistant to let this conversation use AI
                Station capabilities, or Conversation only to talk with the
                model.
              </p>
              {provider.data && (
                <>
                  <p>
                    <span className="chip">LOCAL</span>{" "}
                    <span className="mono">{provider.data.endpoint}</span>
                  </p>
                  {provider.data.error && (
                    <p className="notice">
                      {provider.data.error}. A configured model name can still
                      be saved.
                    </p>
                  )}
                  <SettingsForm
                    key={provider.data.default_model}
                    defaults={{
                      execution_mode: assistant ? "orchestrator" : "local",
                      title: "New conversation",
                      model: provider.data.default_model,
                      system_prompt: "",
                      temperature: 0.7,
                      max_tokens: 2048,
                    }}
                    models={provider.data.models}
                    pending={create.isPending}
                    submit={(body) => create.mutate(body)}
                    label="Create conversation"
                  />
                </>
              )}
              {provider.isPending && <Loading />}
            </div>
          ) : detail.isPending ? (
            <Loading />
          ) : (
            detail.data && (
              <ConversationView
                key={id}
                conversation={detail.data}
                models={provider.data?.models ?? []}
              />
            )
          )}
        </section>
      </div>
    </>
  );
}
function SettingsForm({
  defaults,
  models,
  pending,
  submit,
  label,
}: {
  defaults: Omit<Conversation, "id" | "updated_at">;
  models: string[];
  pending: boolean;
  submit: (body: unknown) => void;
  label: string;
}) {
  const [model, setModel] = useState(defaults.model);
  const [modelPending, setModelPending] = useState(false);
  return (
    <form
      className="image-form chat-settings"
      onSubmit={(e) => {
        e.preventDefault();
        if (pending || modelPending || !model) return;
        const fields = new FormData(e.currentTarget);
        submit({
          execution_mode: fields.get("execution_mode"),
          title: fields.get("title"),
          model,
          system_prompt: fields.get("system_prompt"),
          temperature: Number(fields.get("temperature")),
          max_tokens: Number(fields.get("max_tokens")),
        });
      }}
    >
      <fieldset disabled={pending}>
        <label>
          Mode
          <select
            aria-label="Mode"
            name="execution_mode"
            defaultValue={defaults.execution_mode ?? "local"}
          >
            <option value="orchestrator">Platform assistant</option>
            <option value="local">Conversation only</option>
          </select>
        </label>
        <label>
          Conversation title
          <input
            name="title"
            required
            maxLength={300}
            defaultValue={defaults.title}
          />
        </label>
        <LlamaModels
          value={model}
          label={model === defaults.model ? defaults.model_label : undefined}
          models={models}
          busy={pending}
          onSelect={setModel}
          onBusy={setModelPending}
        />
        <label>
          System prompt
          <textarea
            name="system_prompt"
            rows={3}
            maxLength={8000}
            defaultValue={defaults.system_prompt}
          />
        </label>
        <div className="field-pair">
          <label>
            Temperature
            <input
              name="temperature"
              type="number"
              min={0}
              max={2}
              step={0.1}
              defaultValue={defaults.temperature}
            />
          </label>
          <label>
            Maximum tokens
            <input
              name="max_tokens"
              type="number"
              min={1}
              max={8192}
              defaultValue={defaults.max_tokens}
            />
          </label>
        </div>
        <Button type="submit" disabled={modelPending || !model}>
          {pending ? "Saving…" : label}
        </Button>
      </fieldset>
    </form>
  );
}
function ConversationView({
  conversation,
  models,
}: {
  conversation: Detail;
  models: string[];
}) {
  const cache = useQueryClient();
  const [draft, setDraft] = useState("");
  const [options, setOptions] = useState(emptyOptions);
  const [webEnabled, setWebEnabled] = useState(false);
  const [webQuery, setWebQuery] = useState("");
  const orchestrator = conversation.execution_mode === "orchestrator";
  const [attachments, setAttachments] = useState<TextAttachment[]>([]);
  const [readingAttachment, setReadingAttachment] = useState(false);
  const [modelPending, setModelPending] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const [clipboardError, setClipboardError] = useState<Error | null>(null);
  const refresh = () => {
    void cache.invalidateQueries({
      queryKey: ["conversation", conversation.id],
    });
    void cache.invalidateQueries({ queryKey: ["conversations"] });
  };
  const gitContent =
    options.commit?.message || options.publish?.title || "";
  const gitReady =
    (options.action === "coding.commit" && !!options.commit) ||
    (options.action === "coding.publish" && !!options.publish);
  const canSend =
    options.action === "coding.commit" || options.action === "coding.publish"
      ? gitReady
      : !!draft.trim();
  const send = useMutation({
    mutationFn: () =>
      api<Run>(`/chat/conversations/${conversation.id}/messages`, {
        method: "POST",
        ...json({
          content: draft.trim() || gitContent,
          attachments,
          ...(orchestrator ? options : {}),
          web_search: { enabled: webEnabled, query: webQuery },
        }),
      }),
    onSuccess: () => {
      setDraft("");
      setWebQuery("");
      setAttachments([]);
      setOptions(emptyOptions);
      refresh();
    },
  });
  const stop = useMutation({
    mutationFn: () =>
      api(`/runs/${conversation.active_run?.id}/cancel`, { method: "POST" }),
    onSuccess: refresh,
  });
  const regenerate = useMutation({
    mutationFn: () =>
      api(`/chat/conversations/${conversation.id}/regenerate`, {
        method: "POST",
      }),
    onSuccess: refresh,
  });
  const settings = useMutation({
    mutationFn: (body: unknown) =>
      api(`/chat/conversations/${conversation.id}`, {
        method: "PATCH",
        ...json(body),
      }),
    onSuccess: refresh,
  });
  const busy =
    !!conversation.active_run ||
    send.isPending ||
    regenerate.isPending ||
    readingAttachment ||
    modelPending ||
    settings.isPending;
  const messages = conversation.messages;
  const last = messages.at(-1);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest" });
  }, [last?.content, messages.length]);
  return (
    <>
      <div className="chat-heading">
        <div>
          <h2>{conversation.title}</h2>
          <LlamaModels
            compact
            value={conversation.model}
            label={conversation.model_label}
            models={models}
            busy={busy}
            onBusy={setModelPending}
            onSelect={(model) =>
              settings.mutate({
                model,
                execution_mode: conversation.execution_mode,
                title: conversation.title,
                system_prompt: conversation.system_prompt,
                temperature: conversation.temperature,
                max_tokens: conversation.max_tokens,
              })
            }
          />
        </div>
        {conversation.active_run && (
          <Link to={`/runs/${conversation.active_run.id}`}>
            <Badge status={conversation.active_run.status} />
            {conversation.active_run.executor_type === "chat_summary" &&
              " Updating conversation memory…"}
          </Link>
        )}
      </div>
      <details className="chat-settings-panel">
        <summary>Conversation settings</summary>
        <SettingsForm
          key={conversation.updated_at}
          defaults={conversation}
          models={models}
          pending={busy || settings.isPending}
          submit={(body) => settings.mutate(body)}
          label="Save settings"
        />
      </details>
      <ConversationSummary
        conversationId={conversation.id}
        summary={conversation.summary}
        autoSummary={conversation.auto_summary}
        lastUpdate={conversation.summary_update}
        busy={busy}
      />
      <div className="chat-transcript" aria-live="polite">
        {!messages.length && (
          <Empty title="A fresh perspective starts here">
            {orchestrator
              ? "Describe what you want done. Attach image references, create an agent or select a project for coding."
              : "Send a message to your local model. No external provider is selected."}
          </Empty>
        )}
        {messages
          .filter((message) => !message.metadata.routing_only)
          .map((message) => (
            <article
              className={`chat-message ${message.role} ${message.metadata.superseded ? "superseded" : ""}`}
              key={message.id}
            >
              <div className="row spread">
                <strong>
                  {message.role === "user"
                    ? "You"
                    : orchestrator
                      ? "AI Station"
                      : "Local AI"}
                  {message.metadata.superseded ? " · Previous response" : ""}
                </strong>
                <small className="muted">{time(message.created_at)}</small>
              </div>
              <div className="markdown">
                <Markdown
                  remarkPlugins={[remarkGfm]}
                  rehypePlugins={[rehypeHighlight]}
                  components={{
                    img: ({ alt }) => (
                      <span className="muted">
                        [Image: {alt ?? "remote media"}]
                      </span>
                    ),
                    a: ({ href, children }) => (
                      <a href={href} target="_blank" rel="noreferrer">
                        {children}
                      </a>
                    ),
                  }}
                >
                  {(message.metadata.user_text ?? message.content) ||
                    (message.role === "assistant"
                      ? message.run_status &&
                        ["failed", "canceled", "interrupted"].includes(
                          message.run_status,
                        )
                        ? "No response text was returned."
                        : "Waiting for response…"
                      : "")}
                </Markdown>
              </div>
              <div className="assistant-images">
                {message.metadata.images?.map((image, index) => (
                  <img
                    key={`${image.id}-${index}`}
                    src={`/api/artifacts/${image.id}/file`}
                    alt={`Reference ${index + 1}: ${image.name}`}
                  />
                ))}
              </div>
              {message.role === "assistant" && message.metadata.web_search && (
                <SearchSources result={message.metadata.web_search} />
              )}
              {message.metadata.agent_id && (
                <p>
                  <Link to={`/agents/${message.metadata.agent_id}`}>
                    Review and enable agent
                  </Link>
                </p>
              )}
              <AssistantResults
                result={message}
                inputs={options}
                busy={busy}
                onQueued={orchestrator ? refresh : undefined}
                onUse={
                  orchestrator
                    ? (artifact) =>
                        setOptions((previous) => ({
                          ...previous,
                          ...(artifact.type === "image"
                            ? {
                                image_artifact_ids: [
                                  ...previous.image_artifact_ids,
                                  artifact.id,
                                ],
                              }
                            : { audio_artifact_id: artifact.id }),
                        }))
                    : undefined
                }
              />
              {message.metadata.attachments?.map((attachment) => (
                <div key={attachment.id} className="chat-saved-attachment">
                  <p>
                    <a
                      className="text-link"
                      href={`/api/artifacts/${attachment.id}/file`}
                    >
                      {attachment.name}
                    </a>
                    {" · "}
                    {attachment.size_bytes} bytes
                    {attachment.kind === "pdf" &&
                      " · extracted text, not vision"}
                    {attachment.kind === "image" &&
                      " · stored image, pixels not sent"}
                    {(!attachment.kind || attachment.kind === "text") &&
                      " · saved attachment"}
                  </p>
                  {attachment.kind === "image" && (
                    <img
                      className="chat-attachment-preview"
                      alt={attachment.name}
                      src={`/api/artifacts/${attachment.id}/thumbnail`}
                    />
                  )}
                </div>
              ))}
              {message.role === "assistant" && (
                <div className="message-actions">
                  {message.run_status && <Badge status={message.run_status} />}{" "}
                  {message.metadata.partial && message.content && (
                    <span className="muted">Partial response</span>
                  )}
                  {message.run_id && (
                    <Link to={`/runs/${message.run_id}`}>Inspect run</Link>
                  )}
                  <button
                    className="icon-button"
                    aria-label="Copy response"
                    disabled={!message.content}
                    onClick={() => {
                      void navigator.clipboard
                        .writeText(message.content)
                        .catch(() =>
                          setClipboardError(
                            new Error(
                              "Clipboard unavailable. Select and copy the response text.",
                            ),
                          ),
                        );
                    }}
                  >
                    <Copy size={14} />
                  </button>
                </div>
              )}
              {message.error_message && (
                <p className="notice">{message.error_message}</p>
              )}
            </article>
          ))}
        <div ref={end} />
      </div>
      <div className="chat-composer">
        <ErrorNotice
          error={
            send.error ??
            stop.error ??
            regenerate.error ??
            settings.error ??
            clipboardError
          }
        />
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (canSend && !busy) send.mutate();
          }}
        >
          <label className="sr-only" htmlFor="chat-draft">
            Message
          </label>
          <textarea
            id="chat-draft"
            placeholder={
              orchestrator
                ? "Describe your task — or drop reference images below…"
                : "Ask your local model…"
            }
            rows={3}
            maxLength={32000}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
                e.preventDefault();
                if (canSend && !busy) send.mutate();
              }
            }}
          />
          {orchestrator && (
            <AssistantActions
              value={options}
              sources={messages.flatMap((message) => message.coding_runs ?? [])}
              onChange={(next) => {
                setOptions(next);
                if (
                  !["auto", "chat"].includes(next.action) ||
                  next.image_artifact_ids.length ||
                  next.audio_artifact_id ||
                  next.coding ||
                  next.commit ||
                  next.publish
                )
                  setWebEnabled(false);
              }}
              busy={busy || attachments.length > 0}
              onUploading={setReadingAttachment}
            />
          )}
          {(!orchestrator ||
            !options.action.startsWith("coding.") ||
            attachments.length > 0) && (
            <TextAttachments
              attachments={attachments}
              onChange={setAttachments}
              busy={busy || options.image_artifact_ids.length > 0}
              onReading={setReadingAttachment}
            />
          )}
          {(!orchestrator ||
            (["auto", "chat"].includes(options.action) &&
              !options.image_artifact_ids.length &&
              !options.audio_artifact_id &&
              !options.coding)) && (
            <WebSearchControl
              enabled={webEnabled}
              query={webQuery}
              busy={busy}
              onToggle={setWebEnabled}
              onQuery={setWebQuery}
            />
          )}
          <div className="row spread">
            <span className="muted">
              Ctrl / Cmd + Enter to send · recent context: up to 16 messages
            </span>
            {conversation.active_run ? (
              <Button
                type="button"
                variant="secondary"
                disabled={
                  stop.isPending ||
                  conversation.active_run.status === "cancel_requested"
                }
                onClick={() => stop.mutate()}
              >
                <Square size={14} />
                Stop
              </Button>
            ) : (
              <Button type="submit" disabled={busy || !canSend}>
                <Send size={14} />
                Send
              </Button>
            )}
          </div>
        </form>
        {!!messages.length && !busy && !orchestrator && (
          <Button
            variant="ghost"
            disabled={regenerate.isPending}
            onClick={() => regenerate.mutate()}
          >
            Regenerate last response
          </Button>
        )}
      </div>
    </>
  );
}
