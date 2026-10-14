import {
  useChatDraft,
  chatRequestId,
  clearChatRequest,
  clearChatDraft,
} from "./chat-draft";
import {
  WebSearchControl,
  SearchSources,
  type WebSources,
} from "./ChatWebSearch";
import LlamaModels from "./LlamaModels";
import UnifiedModelPicker from "./UnifiedModelPicker";
import ChatThinking from "./ChatThinking";
import { useThinking } from "./chat-thinking";
import NewChat from "./NewChat";
import ConversationComposer from "./ConversationComposer";
import ChatModeSwitch from "./ChatModeSwitch";
import type { ChatProviderInfo } from "./ChatProviders";
import { emptyOptions } from "./assistant-options";
import AssistantActions, {
  AssistantResults,
  type ActionResult,
  type AssistantOptions,
} from "./AssistantActions";
import { AssistantAgentDraft } from "./AssistantAgentDraft";
import TextAttachments, { type TextAttachment } from "./TextAttachments";
import ConversationSummary, { type Summary } from "./ConversationSummary";
import {
  useEffect,
  useDeferredValue,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { Copy, MessageSquare, Plus, Square } from "lucide-react";
import { api, type Run } from "../api";
import { Badge, Empty, ErrorNotice, Loading } from "../components/common";
import { Button } from "../components/ui/button";
import { time } from "../lib/utils";
import { useListKeyboard } from "./useListKeyboard";
import {
  ConversationModeChoiceList,
  ConversationProviderChoiceList,
  type SavedChatMode,
} from "./ChatSettingsChoiceLists";

type Conversation = {
  id: string;
  execution_mode?: "local" | "orchestrator" | "chat" | "work";
  settings_version?: number;
  title: string;
  provider: string;
  provider_name?: string;
  provider_location?: string;
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
    reasoning_text?: string;
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
type Provider = ChatProviderInfo;
const json = (body: unknown) => ({
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

function ConversationHistory({
  conversations,
  currentId,
  newTo,
  pending,
  onNew,
  search,
  onSearch,
  hasMore,
  loadingMore,
  onMore,
}: {
  conversations: Conversation[];
  currentId?: string;
  newTo: string;
  pending: boolean;
  onNew: () => void;
  search: string;
  onSearch: (value: string) => void;
  hasMore: boolean;
  loadingMore: boolean;
  onMore: () => void;
}) {
  const headingId = useId();
  const labelId = useId();
  const { listRef, onKeyDown, itemProps } = useListKeyboard(
    conversations,
    (row) => row.id,
    { initialKey: currentId },
  );
  return (
    <aside className="panel chat-history">
      <Button asChild>
        <Link to={newTo} onClick={onNew}>
          <Plus size={15} aria-hidden="true" />
          New conversation
        </Link>
      </Button>
      <label className="chat-history-search">
        <span className="sr-only">Search conversations</span>
        <input
          type="search"
          value={search}
          maxLength={200}
          placeholder="Search conversations…"
          onChange={(event) => onSearch(event.target.value)}
        />
      </label>
      {conversations.length ? (
        <section aria-labelledby={headingId}>
          <h2 id={headingId} className="sr-only">
            Conversations
          </h2>
          <p id={labelId} className="sr-only">
            Arrow keys choose a conversation while the list is focused. Enter
            opens it.
          </p>
          <div
            ref={listRef}
            className="chat-conversations"
            aria-labelledby={labelId}
            onKeyDown={onKeyDown}
          >
            {conversations.map((row, i) => {
              return (
                <Link
                  className={row.id === currentId ? "selected" : ""}
                  key={row.id}
                  to={`/chat/${row.id}`}
                  aria-label={`Inspect ${row.title} ${row.id.slice(0, 8)}`}
                  {...itemProps(i, row.id)}
                >
                  <MessageSquare size={15} aria-hidden="true" />
                  <span>
                    <strong>{row.title}</strong>
                    <small>
                      {row.model_label ?? row.model} · {time(row.updated_at)}
                    </small>
                  </span>
                </Link>
              );
            })}
          </div>
        </section>
      ) : (
        !pending && (
          <p className="muted">
            {search.trim()
              ? "No matching conversations."
              : "Your conversations will stay here after a restart."}
          </p>
        )
      )}
      {hasMore && (
        <Button
          type="button"
          variant="secondary"
          disabled={loadingMore}
          onClick={onMore}
        >
          {loadingMore ? "Loading…" : "Load older conversations"}
        </Button>
      )}
    </aside>
  );
}

export default function Chat({ assistant = false }: { assistant?: boolean }) {
  const { id } = useParams();
  const cache = useQueryClient();
  const navigate = useNavigate();
  const [newDraftKey, setNewDraftKey] = useState(0);
  const [historySearch, setHistorySearch] = useState("");
  const historyQuery = useDeferredValue(historySearch.trim());
  const conversations = useInfiniteQuery({
    queryKey: ["conversations", "history", historyQuery],
    initialPageParam: null as { at: string; id: string } | null,
    queryFn: ({ pageParam }) => {
      const query = new URLSearchParams();
      if (historyQuery) query.set("q", historyQuery);
      if (pageParam) {
        query.set("before", pageParam.at);
        query.set("before_id", pageParam.id);
      }
      return api<Conversation[]>(
        "/chat/conversations" + (query.size ? "?" + query : ""),
      );
    },
    getNextPageParam: (last) =>
      last.length === 100
        ? { at: last[last.length - 1].updated_at, id: last[last.length - 1].id }
        : undefined,
    refetchInterval: 5000,
  });
  const historyRows = Array.from(
    new Map(
      (conversations.data?.pages.flat() ?? []).map((row) => [row.id, row]),
    ).values(),
  );
  const providers = useQuery({
    queryKey: ["chat-providers"],
    queryFn: () => api<Provider[]>("/chat/providers"),
    retry: false,
  });
  const [providerKey, setProviderKey] = useState("");
  const selectedKey =
    providerKey ||
    providers.data?.find((row) => row.builtin)?.key ||
    providers.data?.find((row) => row.location === "local" && row.enabled)
      ?.key ||
    "";
  const provider = useQuery({
    queryKey: ["chat-provider", selectedKey],
    queryFn: () => api<Provider>(`/chat/providers/${selectedKey}`),
    enabled: !!selectedKey,
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
  return (
    <>
      <ErrorNotice
        error={
          conversations.error ??
          providers.error ??
          provider.error ??
          (id ? detail.error : null)
        }
      />
      <div
        className={`chat-layout chat-entry-layout ${id ? "chat-conversation-layout" : ""}`}
      >
        <details className="chat-entry-history">
          <summary>Recent conversations</summary>
          <ConversationHistory
            conversations={historyRows}
            currentId={id}
            newTo={assistant ? "/" : "/chat"}
            pending={conversations.isPending}
            search={historySearch}
            onSearch={setHistorySearch}
            hasMore={conversations.hasNextPage}
            loadingMore={conversations.isFetchingNextPage}
            onMore={() => {
              void conversations.fetchNextPage();
            }}
            onNew={() => {
              clearChatDraft("new");
              clearChatRequest("new");
              setNewDraftKey((value) => value + 1);
            }}
          />
        </details>
        <section className="chat-main panel">
          {!id ? (
            <NewChat
              key={newDraftKey}
              providers={providers.data ?? []}
              provider={provider.data}
              onProviderChange={setProviderKey}
              onAccepted={(value) => navigate(`/chat/${value}`)}
            />
          ) : detail.isPending ? (
            <Loading />
          ) : (
            detail.data && (
              <ConversationView
                key={id}
                conversation={detail.data}
                providers={providers.data ?? []}
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
  providers,
  provider,
  onProviderChange,
  models,
  pending,
  submit,
  label,
}: {
  defaults: Omit<Conversation, "id" | "updated_at">;
  providers: Provider[];
  provider?: Provider;
  onProviderChange: (key: string) => void;
  models: string[];
  pending: boolean;
  submit: (body: unknown) => void;
  label: string;
}) {
  const [model, setModel] = useState(defaults.model);
  const [modelPending, setModelPending] = useState(false);
  const [mode, setMode] = useState<SavedChatMode>(
    defaults.execution_mode === "work" ||
      defaults.execution_mode === "orchestrator"
      ? "orchestrator"
      : "local",
  );
  const localBuiltin = provider?.builtin && provider.location === "local";
  return (
    <form
      className="image-form chat-settings"
      onSubmit={(e) => {
        e.preventDefault();
        if (pending || modelPending || !model) return;
        const fields = new FormData(e.currentTarget);
        submit({
          execution_mode: mode,
          title: fields.get("title"),
          provider: defaults.provider,
          model,
          system_prompt: fields.get("system_prompt"),
          temperature: Number(fields.get("temperature")),
          max_tokens: Number(fields.get("max_tokens")),
        });
      }}
    >
      <fieldset disabled={pending}>
        {localBuiltin ? (
          <LlamaModels
            selectionOnly
            value={model}
            label={model === defaults.model ? defaults.model_label : undefined}
            models={models}
            busy={pending}
            onSelect={setModel}
            onBusy={setModelPending}
          />
        ) : (
          <label>
            Model
            <input
              aria-label="Model"
              list="chat-provider-models"
              required
              maxLength={200}
              value={model}
              onChange={(event) => setModel(event.target.value)}
            />
            <datalist id="chat-provider-models">
              {models.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
          </label>
        )}
        <details className="chat-advanced-settings">
          <summary>Advanced settings</summary>
          <div>
            <span>Mode</span>
            <ConversationModeChoiceList
              value={mode}
              disabled={pending}
              onChange={setMode}
            />
          </div>
          <label>
            Conversation title
            <input
              name="title"
              required
              maxLength={300}
              defaultValue={defaults.title}
            />
          </label>
          <div>
            <span>Provider</span>
            <ConversationProviderChoiceList
              value={defaults.provider}
              providers={providers}
              disabled={pending}
              onChange={(key) => {
                onProviderChange(key);
                setModel("");
              }}
            />
          </div>
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
        </details>
        <Button type="submit" disabled={modelPending || !model}>
          {pending ? "Saving…" : label}
        </Button>
      </fieldset>
    </form>
  );
}
function SavedAttachments({
  attachments,
}: {
  attachments: NonNullable<Message["metadata"]["attachments"]>;
}) {
  const labelId = useId();
  const { listRef, onKeyDown, itemProps } = useListKeyboard(
    attachments,
    (item) => item.id,
  );
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    event.stopPropagation();
    onKeyDown(event);
  };
  return (
    <>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a saved attachment while the list is focused. Enter
        opens the selected file. There is no inspectable attachment Run.
      </p>
      <div
        ref={listRef}
        className="chat-saved-attachment-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {attachments.map((attachment, i) => {
          const shortId = attachment.id.slice(0, 8);
          const kind =
            attachment.kind === "pdf"
              ? "extracted text, not vision"
              : attachment.kind === "image"
                ? "stored image, pixels not sent"
                : "saved attachment";
          return (
            <a
              key={attachment.id}
              className="chat-saved-attachment"
              href={`/api/artifacts/${attachment.id}/file`}
              aria-label={`Saved attachment ${attachment.name} ${shortId}`}
              {...itemProps(i, attachment.id)}
            >
              <strong>{attachment.name}</strong>
              <span className="muted">
                {attachment.size_bytes} bytes · {kind}
              </span>
              {attachment.kind === "image" && (
                <img
                  className="chat-attachment-preview"
                  alt=""
                  src={`/api/artifacts/${attachment.id}/thumbnail`}
                />
              )}
            </a>
          );
        })}
      </div>
    </>
  );
}
function speakerName(message: Message, orchestrator: boolean) {
  return message.role === "user"
    ? "You"
    : orchestrator
      ? "AI Station"
      : "Local AI";
}
function Transcript({
  messages,
  orchestrator,
  options,
  busy,
  refresh,
  setOptions,
  setClipboardError,
  emptyHint,
  onProject,
}: {
  messages: Message[];
  orchestrator: boolean;
  options: AssistantOptions;
  busy: boolean;
  refresh: () => void;
  setOptions: (
    update: (previous: AssistantOptions) => AssistantOptions,
  ) => void;
  setClipboardError: (error: Error | null) => void;
  emptyHint: string;
  onProject?: (project: {
    id: string;
    name: string;
    updated_at: string;
  }) => void;
}) {
  const headingId = useId();
  const labelId = useId();
  const end = useRef<HTMLDivElement>(null);
  const viewport = useRef<HTMLElement>(null);
  const followLatest = useRef(true);
  const [readingEarlier, setReadingEarlier] = useState(false);
  const visible = messages.filter((message) => !message.metadata.routing_only);
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    visible,
    (message) => message.id,
    { initialKey: visible.at(-1)?.id, fallback: "last" },
  );
  const selected = visible[index];
  const navigate = useNavigate();
  useEffect(() => {
    if (followLatest.current && viewport.current)
      viewport.current.scrollTop = viewport.current.scrollHeight;
  }, [messages]);
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    if (
      target.closest(
        "a, button, textarea, input, select, summary, pre, code, [contenteditable='true']",
      )
    )
      return;
    if (window.getSelection()?.isCollapsed === false) return;
    onKeyDown(event);
    if (event.key !== "Enter" || event.defaultPrevented) return;
    if (selected?.run_id) {
      event.preventDefault();
      navigate(`/runs/${selected.run_id}`);
    }
  };
  return (
    <section
      ref={viewport}
      className="chat-transcript"
      aria-labelledby={headingId}
      onScroll={(event) => {
        const panel = event.currentTarget;
        followLatest.current =
          panel.scrollHeight - panel.scrollTop - panel.clientHeight < 80;
        setReadingEarlier(!followLatest.current);
      }}
    >
      <h2 id={headingId} className="sr-only">
        Messages
      </h2>
      {visible.length ? (
        <p id={labelId} className="sr-only">
          Arrow keys choose a message while the transcript is focused. Enter
          inspects its Run when one exists.
        </p>
      ) : (
        <Empty title="A fresh perspective starts here">{emptyHint}</Empty>
      )}
      <div
        ref={listRef}
        className="chat-messages"
        aria-labelledby={visible.length ? labelId : undefined}
        onKeyDown={handleKey}
      >
        {visible.map((message, i) => {
          const current = i === index;
          const speaker = speakerName(message, orchestrator);
          const shortId = message.id.slice(0, 8);
          return (
            <article
              className={`chat-message ${message.role} ${message.metadata.superseded ? "superseded" : ""}`}
              key={message.id}
              aria-label={`Message ${speaker} ${shortId}`}
              {...itemProps(i, message.id)}
            >
              <div className="row spread">
                <strong>
                  {speaker}
                  {message.metadata.superseded ? " · Previous response" : ""}
                </strong>
                <small className="muted">{time(message.created_at)}</small>
              </div>
              {message.metadata.reasoning_text && (
                <details className="message-thinking">
                  <summary>Thinking</summary>
                  <p>{message.metadata.reasoning_text}</p>
                </details>
              )}
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
                {message.metadata.images?.map((image, imageIndex) => (
                  <img
                    key={`${image.id}-${imageIndex}`}
                    src={`/api/artifacts/${image.id}/file`}
                    alt={`Reference ${imageIndex + 1}: ${image.name}`}
                  />
                ))}
              </div>
              {message.role === "assistant" && message.metadata.web_search && (
                <SearchSources result={message.metadata.web_search} />
              )}
              {message.metadata.agent_id && (
                <AssistantAgentDraft
                  agentId={message.metadata.agent_id}
                  tabIndex={current ? 0 : -1}
                />
              )}
              <AssistantResults
                result={message}
                inputs={options}
                busy={busy}
                onQueued={orchestrator ? refresh : undefined}
                onProject={onProject}
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
              {message.metadata.attachments?.length ? (
                <SavedAttachments attachments={message.metadata.attachments} />
              ) : null}
              {message.role === "assistant" && (
                <div className="message-actions">
                  {message.run_status && <Badge status={message.run_status} />}{" "}
                  {message.metadata.partial && message.content && (
                    <span className="muted">Partial response</span>
                  )}
                  {message.run_id && (
                    <Link
                      to={`/runs/${message.run_id}`}
                      tabIndex={current ? 0 : -1}
                      aria-label={`Inspect run ${speaker} ${shortId}`}
                    >
                      Inspect run
                    </Link>
                  )}
                  <button
                    className="icon-button"
                    aria-label={`Copy ${speaker} ${shortId}`}
                    tabIndex={current ? 0 : -1}
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
                    <Copy size={14} aria-hidden="true" />
                  </button>
                </div>
              )}
              {message.error_message && (
                <p className="notice">{message.error_message}</p>
              )}
            </article>
          );
        })}
        <div ref={end} />
      </div>
      {readingEarlier && (
        <Button
          className="chat-jump-latest"
          variant="secondary"
          onClick={() => {
            followLatest.current = true;
            setReadingEarlier(false);
            if (viewport.current)
              viewport.current.scrollTop = viewport.current.scrollHeight;
          }}
        >
          Jump to latest
        </Button>
      )}
    </section>
  );
}
function ConversationView({
  conversation,
  providers,
}: {
  conversation: Detail;
  providers: Provider[];
}) {
  const cache = useQueryClient();
  const selected = useQuery({
    queryKey: ["chat-provider", conversation.provider],
    queryFn: () => api<Provider>(`/chat/providers/${conversation.provider}`),
    retry: false,
  });
  const preferences = useQuery({
    queryKey: ["chat-preferences"],
    queryFn: () =>
      api<{ send_key: "enter" | "ctrl-enter" }>("/chat/preferences"),
  });
  const models = selected.data?.models ?? [];
  const draftState = useChatDraft(conversation.id);
  const submittedDraft = useRef("");
  const draft = draftState.value,
    setDraft = draftState.update;
  const [options, setOptions] = useState(emptyOptions);
  const [webEnabled, setWebEnabled] = useState(false);
  const [projectSelectionVersion, setProjectSelectionVersion] = useState(0);
  const [webQuery, setWebQuery] = useState("");
  const orchestrator = ["work", "orchestrator"].includes(
    conversation.execution_mode ?? "local",
  );
  const [turnMode, setTurnMode] = useState<"chat" | "work">(
    orchestrator ? "work" : "chat",
  );
  const assistantTurn = true;
  const pendingRequest = useRef<{ body: string; id: string } | null>(null);
  const [attachments, setAttachments] = useState<TextAttachment[]>([]);
  const [readingAttachment, setReadingAttachment] = useState(false);
  const [clipboardError, setClipboardError] = useState<Error | null>(null);
  const refresh = () => {
    void cache.invalidateQueries({
      queryKey: ["conversation", conversation.id],
    });
    void cache.invalidateQueries({ queryKey: ["conversations"] });
  };
  const gitContent = options.commit?.message || options.publish?.title || "";
  const runtimeReady =
    (options.action === "runtime.load" && !!options.load) ||
    (options.action === "runtime.stop" && !!options.stop);
  const gitReady =
    (options.action === "coding.commit" && !!options.commit) ||
    (options.action === "coding.publish" && !!options.publish);
  const canSend =
    assistantTurn && options.action === "project.create_code"
      ? !!draft.trim() &&
        !!options.new_project?.name.trim() &&
        (options.new_project.executor === "local" ||
          options.new_project.external_ai)
      : assistantTurn && options.action === "system.inspect"
        ? true
        : assistantTurn && options.action.startsWith("runtime.")
          ? runtimeReady
          : assistantTurn &&
              (options.action === "coding.commit" ||
                options.action === "coding.publish")
            ? gitReady
            : !!draft.trim();
  const thinking = useThinking(
    conversation.model,
    turnMode === "chat" &&
      ["auto", "chat"].includes(options.action) &&
      !options.image_artifact_ids.length &&
      !attachments.some((item) => item.kind === "image"),
    conversation.max_tokens,
  );
  const send = useMutation({
    mutationFn: async () => {
      submittedDraft.current = draft;
      const values = {
        content:
          draft.trim() ||
          gitContent ||
          (options.action === "runtime.load"
            ? "Load the selected local GGUF"
            : options.action === "runtime.stop"
              ? "Unload the selected owned llama.cpp instance"
              : options.action === "system.inspect"
                ? "Inspect current workstation telemetry and activity"
                : ""),
        conversation_id: conversation.id,
        expected_settings_version: conversation.settings_version ?? 1,
        ...(selected.data?.updated_at
          ? { expected_provider_version: selected.data.updated_at }
          : {}),
        attachments,
        execution_mode: turnMode,
        ...(thinking.enabled
          ? { reasoning: { enabled: true, budget: 256 } }
          : {}),
        ...(assistantTurn ? options : {}),
        web_search: { enabled: webEnabled, query: webQuery },
      };
      const body = JSON.stringify(values);
      if (pendingRequest.current?.body !== body)
        pendingRequest.current = {
          body,
          id: await chatRequestId(conversation.id, body),
        };
      return api("/chat/turns", {
        method: "POST",
        ...json({
          ...values,
          client_request_id: pendingRequest.current.id,
        }),
      });
    },
    onSuccess: () => {
      pendingRequest.current = null;
      clearChatRequest(conversation.id);
      draftState.accept(submittedDraft.current);
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
    settings.isPending;
  const messages = conversation.messages;
  return (
    <div className="conversation-shell">
      <div className="chat-heading">
        <div>
          <h2>{conversation.title}</h2>
          <UnifiedModelPicker
            providerKey={conversation.provider}
            modelKey={conversation.model}
            label={conversation.model_label}
            location={
              conversation.provider_location as "local" | "external" | undefined
            }
            busy={busy}
            onSelect={(choice) =>
              settings.mutate({
                model: choice.model_key,
                provider: choice.provider_key,
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
      {thinking.available && (
        <ChatThinking
          value={thinking.enabled}
          busy={busy}
          blocked={thinking.blocked}
          onChange={thinking.onChange}
        />
      )}
      <details className="chat-settings-panel">
        <summary>Conversation settings</summary>
        <SettingsForm
          key={conversation.updated_at}
          defaults={conversation}
          providers={providers}
          provider={selected.data}
          onProviderChange={(key) =>
            settings.mutate({
              provider: key,
              model: conversation.model,
              execution_mode: conversation.execution_mode,
              title: conversation.title,
              system_prompt: conversation.system_prompt,
              temperature: conversation.temperature,
              max_tokens: conversation.max_tokens,
            })
          }
          models={models}
          pending={busy || settings.isPending}
          submit={(body) => settings.mutate(body)}
          label="Save settings"
        />
      </details>
      <details className="chat-settings-panel">
        <summary>Memory &amp; context</summary>
        <ConversationSummary
          conversationId={conversation.id}
          summary={conversation.summary}
          autoSummary={conversation.auto_summary}
          lastUpdate={conversation.summary_update}
          busy={busy}
        />
      </details>
      <Transcript
        messages={messages}
        orchestrator={orchestrator}
        options={options}
        busy={busy}
        refresh={refresh}
        setOptions={setOptions}
        setClipboardError={setClipboardError}
        emptyHint={
          orchestrator
            ? "Describe what you want done. Attach image references, create an agent or select a project for coding."
            : conversation.provider_location === "external"
              ? "Send a message through the selected external provider. The secret value is never displayed."
              : "Send a message to the selected local provider."
        }
        onProject={
          conversation.provider_location !== "external"
            ? (project) => {
                setProjectSelectionVersion((current) => current + 1);
                setTurnMode("work");
                setWebEnabled(false);
                void cache.invalidateQueries({ queryKey: ["coding-projects"] });
                void cache.invalidateQueries({ queryKey: ["projects"] });
                setOptions({
                  action: "coding.local",
                  new_project: null,
                  image_artifact_ids: [],
                  audio_artifact_id: null,
                  coding: {
                    project_id: project.id,
                    expected_updated_at: project.updated_at,
                    files: [],
                    external_ai: false,
                    explore: true,
                  },
                  commit: null,
                  publish: null,
                  load: null,
                  stop: null,
                  upscale_result: false,
                  speech_text: null,
                });
              }
            : undefined
        }
      />
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
        {draftState.restored && (
          <p className="muted">
            Draft text restored. Reattach files and confirm tools before
            sending.
          </p>
        )}
        <ConversationComposer
          id="chat-draft"
          value={draft}
          onChange={setDraft}
          onSend={() => send.mutate()}
          canSend={canSend}
          busy={busy}
          sendKey={preferences.data?.send_key}
          placeholder={
            assistantTurn
              ? options.action === "image.generate_video"
                ? "Describe the scene and motion…"
                : options.action === "project.create_code"
                  ? "Describe what your new project should do…"
                  : options.action === "project.create"
                    ? "Name your project — for example Weather Station"
                    : "Describe your task — or attach reference images…"
              : "Ask your local model…"
          }
          tools={
            <>
              {assistantTurn && (
                <AssistantActions
                  key={projectSelectionVersion}
                  value={options}
                  allowWork={turnMode === "work"}
                  sources={messages.flatMap(
                    (message) => message.coding_runs ?? [],
                  )}
                  onChange={(next) => {
                    setOptions(next);
                    if (
                      ![
                        "auto",
                        "chat",
                        "image.generate",
                        "image.generate_video",
                      ].includes(next.action) ||
                      next.image_artifact_ids.length ||
                      next.audio_artifact_id ||
                      next.coding ||
                      next.commit ||
                      next.publish ||
                      next.load ||
                      next.stop ||
                      next.upscale_result
                    )
                      setWebEnabled(false);
                  }}
                  busy={busy || attachments.length > 0}
                  onUploading={setReadingAttachment}
                />
              )}
              {(!assistantTurn ||
                !(
                  options.action.startsWith("coding.") ||
                  options.action.startsWith("runtime.") ||
                  options.action === "system.inspect" ||
                  options.action === "image.generate_video" ||
                  options.action === "project.create" ||
                  options.action === "project.create_code"
                ) ||
                attachments.length > 0) && (
                <TextAttachments
                  attachments={attachments}
                  onChange={setAttachments}
                  busy={busy || options.image_artifact_ids.length > 0}
                  onReading={setReadingAttachment}
                />
              )}
            </>
          }
          controls={
            <>
              <ChatModeSwitch
                value={turnMode}
                disabled={busy}
                onChange={(next) => {
                  setTurnMode(next);
                  setOptions(emptyOptions);
                }}
              />
              {(!assistantTurn ||
                ([
                  "auto",
                  "chat",
                  "image.generate",
                  "image.generate_video",
                ].includes(options.action) &&
                  !options.image_artifact_ids.length &&
                  !options.audio_artifact_id &&
                  !options.coding &&
                  !options.upscale_result)) && (
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
          sendButton={
            conversation.active_run ? (
              <Button
                type="button"
                variant="secondary"
                disabled={
                  stop.isPending ||
                  conversation.active_run.status === "cancel_requested"
                }
                onClick={() => stop.mutate()}
              >
                <Square size={14} /> Stop
              </Button>
            ) : undefined
          }
        />
        {!!messages.length &&
          !busy &&
          !messages.filter((m) => m.role === "assistant").at(-1)?.metadata
            .orchestration && (
            <Button
              variant="ghost"
              disabled={regenerate.isPending}
              onClick={() => regenerate.mutate()}
            >
              Regenerate last response
            </Button>
          )}
      </div>
    </div>
  );
}
