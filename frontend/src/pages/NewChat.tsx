import { browserTimezone } from "./AgentCronFields";
import { useConversationAttachmentUpload } from "./attachment-upload";
import { useDataInputs } from "./useDataInputs";
import { useChatDraft, chatRequestId, clearChatRequest } from "./chat-draft";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Button } from "../components/ui/button";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorNotice } from "../components/common";
import UnifiedModelPicker from "./UnifiedModelPicker";
import ChatThinking from "./ChatThinking";
import { useThinking } from "./chat-thinking";
import ConversationComposer from "./ConversationComposer";
import { musicScopeReady } from "./music-scope";
import AssistantActions from "./AssistantActions";
import { acceptsLocalAttachments, emptyOptions } from "./assistant-options";
import TextAttachments, { type TextAttachment } from "./TextAttachments";
import { useWebSearch } from "./useWebSearch";
import { WebSearchControl } from "./ChatWebSearch";
import type { ChatProviderInfo } from "./ChatProviders";

type WorkDraft = {
  task_id: string;
  project_name: string;
  title: string;
  expected_run_id: string;
  executor: string;
  model: string;
  model_label?: string;
  external: boolean;
  ready: boolean;
  reason: string | null;
};

type Preferences = {
  version: number;
  mode: "assistant" | "chat" | "work";
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
  const [params, setParams] = useSearchParams();
  const workTaskId = params.get("work_task");
  const workspace = useQuery({
    queryKey: ["work-draft", workTaskId],
    enabled: !!workTaskId,
    queryFn: () =>
      api<WorkDraft>(`/coding/sessions/${workTaskId}/work-context`),
  });
  useEffect(() => {
    if (!workTaskId || !workspace.data || params.get("work_run")) return;
    const values = new URLSearchParams(params);
    values.set("work_run", workspace.data.expected_run_id);
    setParams(values, { replace: true });
  }, [workTaskId, workspace.data, params, setParams]);
  const expectedWorkRun = params.get("work_run");
  const [shareCode, setShareCode] = useState(false);
  const localProvider = providers.find(
    (item) => item.key === "local-openai-compatible",
  );
  const activeProvider = workTaskId ? localProvider : provider;
  const clearWorkScope = () => {
    const values = new URLSearchParams(params);
    values.delete("work_task");
    values.delete("work_run");
    values.delete("mode");
    setParams(values);
  };
  const preferences = useQuery({
    queryKey: ["chat-preferences"],
    queryFn: () => api<Preferences>("/chat/preferences"),
  });
  const initialized = useRef(false);
  const pendingRequest = useRef<{ body: string; id: string } | null>(null);
  const mode = "assistant" as const;
  const [selection, setSelection] = useState<{
    provider: string;
    model: string;
    version?: string;
    label?: string;
    location?: "local" | "external";
  } | null>(null);
  const draftState = useChatDraft("new");
  const submittedDraft = useRef("");
  const draft = draftState.value,
    setDraft = draftState.update;
  const [options, setOptions] = useState(emptyOptions);
  const dataInputs = useDataInputs(options.data);
  const dataReady = options.action !== "data.analyze" || dataInputs.ready;
  const [attachments, setAttachments] = useState<TextAttachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const web = useWebSearch(!attachments.length);
  const webEnabled = !workTaskId && web.enabled;
  const setWebEnabled = web.setEnabled;
  const [webQuery, setWebQuery] = useState("");
  const attachmentUpload = useConversationAttachmentUpload((selection) => {
    setOptions(
      selection.kind === "data"
        ? { ...emptyOptions, action: "data.analyze", data: selection.scope }
        : selection.kind === "audio"
          ? { ...emptyOptions, audio_artifact_id: selection.id }
          : {
              ...emptyOptions,
              action: options.action === "chat" ? "chat" : "auto",
              image_artifact_ids: selection.ids,
            },
    );
    setWebEnabled(false);
    setWebQuery("");
    web.setRenderPages(false);
  });
  useEffect(() => {
    if (
      workTaskId ||
      initialized.current ||
      !preferences.data ||
      !providers.length
    )
      return;
    initialized.current = true;
    const saved = preferences.data;
    if (
      saved.model &&
      providers.some((p) => p.key === saved.provider && p.enabled)
    ) {
      onProviderChange(saved.provider);
    }
  }, [preferences.data, providers, onProviderChange, workTaskId]);
  const conversationModel =
    selection && selection.provider === provider?.key
      ? selection.model
      : preferences.data?.provider === provider?.key && preferences.data?.model
        ? preferences.data.model
        : provider?.default_model || provider?.models?.[0] || "";
  const model = workTaskId
    ? workspace.data?.executor === "local"
      ? workspace.data.model
      : localProvider?.default_model || "local"
    : conversationModel;
  const thinking = useThinking(
    model,
    ["auto", "chat"].includes(options.action) &&
      !options.audio_artifact_id &&
      !options.image_artifact_ids.length &&
      !attachments.some((item) => item.kind === "image"),
  );
  const send = useMutation({
    mutationFn: async () => {
      submittedDraft.current = draft;
      const providerVersion = workTaskId
        ? activeProvider?.updated_at
        : (selection?.version ?? provider?.updated_at);
      const values = {
        selection: {
          execution_mode: mode,
          provider: activeProvider?.key ?? "local-openai-compatible",
          model,
          ...(workTaskId && workspace.data
            ? { title: workspace.data.title.slice(0, 300) }
            : {}),
        },
        ...(providerVersion
          ? { expected_provider_version: providerVersion }
          : {}),
        execution_mode: mode,
        schedule_timezone: browserTimezone(),
        ...(thinking.enabled
          ? { reasoning: { enabled: true, budget: 256 } }
          : {}),
        content: draft.trim(),
        attachments,
        ...options,
        ...(["project.create", "project.create_code"].includes(
          options.action,
        ) && !options.data
          ? {
              project_defaults: {
                auto_install_dependencies: true,
                auto_validate: true,
              },
            }
          : {}),
        ...(workTaskId && workspace.data
          ? {
              continuation: {
                task_id: workspace.data.task_id,
                expected_run_id: expectedWorkRun,
                external_ai: shareCode,
              },
            }
          : {}),
        web_search: {
          enabled: webEnabled,
          query: webQuery,
          ...(webEnabled && web.renderPages && !webQuery.trim()
            ? { render_pages: true }
            : {}),
        },
      };
      const body = JSON.stringify(values);
      if (pendingRequest.current?.body !== body)
        pendingRequest.current = { body, id: await chatRequestId("new", body) };
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
      pendingRequest.current = null;
      draftState.accept(submittedDraft.current);
      clearChatRequest("new");
      void cache.invalidateQueries({ queryKey: ["chat-preferences"] });
      void cache.invalidateQueries({ queryKey: ["conversations"] });
      onAccepted(receipt.conversation_id);
    },
  });
  const busy =
    attachmentUpload.isPending ||
    send.isPending ||
    web.busy ||
    uploading ||
    preferences.isPending ||
    (!!workTaskId && workspace.isPending);
  const canSend =
    dataReady &&
    musicScopeReady(options, draft) &&
    !!draft.trim() &&
    !!model &&
    (workTaskId
      ? !!workspace.data?.ready &&
        !!expectedWorkRun &&
        workspace.data.expected_run_id === expectedWorkRun &&
        draft.trim().length <= 4000 &&
        (!workspace.data.external || shareCode)
      : !!provider?.enabled &&
        (provider.secret_source === "none" || provider.secret_present)) &&
    !busy &&
    (options.action !== "github.inspect" || !!options.github) &&
    (options.action !== "project.create_code" ||
      (!!options.new_project?.name.trim() &&
        (options.new_project.executor === "local" ||
          options.new_project.external_ai)));
  return (
    <section className="new-chat" aria-label="New conversation">
      <h1>
        {workTaskId ? "Continue your project" : "What would you like to do?"}
      </h1>
      <p className="muted">
        {workTaskId
          ? "Keep building in the same workspace."
          : "Ask a question or describe what you want to create."}
      </p>
      <div className="new-chat-controls">
        {workTaskId ? (
          <p className="muted">
            Task model:{" "}
            <strong>
              {workspace.data?.model_label ||
                workspace.data?.model ||
                "Loading workspace…"}
            </strong>
          </p>
        ) : (
          <UnifiedModelPicker
            providerKey={selection?.provider ?? provider?.key ?? ""}
            modelKey={model}
            label={selection?.label}
            location={selection?.location ?? provider?.location}
            busy={send.isPending}
            onSelect={(choice) => {
              onProviderChange(choice.provider_key);
              setSelection({
                provider: choice.provider_key,
                model: choice.model_key,
                version: choice.config_version,
                label: choice.display_name,
                location: choice.location,
              });
            }}
          />
        )}
      </div>
      {workTaskId && workspace.data && (
        <section
          className="work-context-card"
          aria-label="Selected coding task"
        >
          <strong>{workspace.data.project_name}</strong>
          <p>{workspace.data.title}</p>
          <p className="muted">
            {workspace.data.executor === "local"
              ? "Local AI"
              : workspace.data.executor}{" "}
            · Same branch and workspace
          </p>
          <div className="row">
            <Link to={`/coding/${workspace.data.task_id}`}>Open workspace</Link>
            <Button
              type="button"
              variant="ghost"
              disabled={busy}
              onClick={() => clearWorkScope()}
            >
              General conversation
            </Button>
          </div>
          {expectedWorkRun &&
            workspace.data.expected_run_id !== expectedWorkRun && (
              <p className="notice">
                The coding task changed since this draft opened. Open its
                workspace to continue from the latest result.
              </p>
            )}
          {workspace.data.reason && (
            <p className="notice">{workspace.data.reason}</p>
          )}
          {workspace.data.external && (
            <label className="work-context-consent">
              <input
                type="checkbox"
                checked={shareCode}
                disabled={busy}
                onChange={(event) => setShareCode(event.target.checked)}
              />
              Share this prompt and relevant source with{" "}
              {workspace.data.executor}.
            </label>
          )}
        </section>
      )}
      {thinking.available && !workTaskId && (
        <ChatThinking
          value={thinking.enabled}
          busy={send.isPending}
          blocked={thinking.blocked}
          onChange={thinking.onChange}
        />
      )}
      {draftState.restored && (
        <p className="muted">
          Draft text restored. Reattach files and confirm tools before sending.
        </p>
      )}
      <ConversationComposer
        permissionNote={
          options.action === "project.create_code"
            ? "New projects include public package preparation and isolated build/test checks. Advanced project settings can override this."
            : undefined
        }
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
          workTaskId
            ? "Describe the next change in this project…"
            : "Ask a question or describe what to create…"
        }
        tools={
          workTaskId ? undefined : (
            <>
              <AssistantActions
                description={draft}
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
                allowWork
                busy={busy || attachments.length > 0}
                onUploading={setUploading}
              />
              {options.action !== "project.create_code" &&
                options.action !== "github.inspect" &&
                options.action !== "audio.transcribe" &&
                options.action !== "audio.analyze" &&
                options.action !== "audio.music" &&
                options.action !== "data.analyze" &&
                !options.image_artifact_ids.length &&
                !options.audio_artifact_id && (
                  <TextAttachments
                    uploadErrorsHandled
                    attachments={attachments}
                    onChange={setAttachments}
                    busy={send.isPending}
                    onReading={setUploading}
                    onDataFiles={
                      acceptsLocalAttachments(options) &&
                      !webQuery.trim() &&
                      !web.renderPages
                        ? (files) =>
                            attachmentUpload.mutateAsync({
                              kind: "data",
                              files,
                            })
                        : undefined
                    }
                    onImageFiles={
                      acceptsLocalAttachments(options) &&
                      !webQuery.trim() &&
                      !web.renderPages
                        ? (files) =>
                            attachmentUpload.mutateAsync({
                              kind: "images",
                              files,
                            })
                        : undefined
                    }
                    onRecordingFiles={
                      acceptsLocalAttachments(options) &&
                      !webQuery.trim() &&
                      !web.renderPages
                        ? (files) =>
                            attachmentUpload.mutateAsync({
                              kind: "audio",
                              files,
                            })
                        : undefined
                    }
                  />
                )}
            </>
          )
        }
        controls={
          workTaskId ? undefined : (
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
                    onToggle={web.onToggle}
                    onQuery={setWebQuery}
                    renderPages={web.renderPages}
                    onRenderPages={web.setRenderPages}
                  />
                )}
            </>
          )
        }
      />
      {!workTaskId && provider?.location === "external" && (
        <p className="notice">
          External AI · Your message and selected attachments will be sent to{" "}
          {provider.name}.
        </p>
      )}
      {!model && (
        <p className="muted">Choose an available model to send your message.</p>
      )}
      <ErrorNotice
        error={
          send.error ??
          attachmentUpload.error ??
          web.error ??
          preferences.error ??
          workspace.error
        }
      />
    </section>
  );
}
