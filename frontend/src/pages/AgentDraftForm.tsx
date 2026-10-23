import { browserTimezone, ScheduleTimezoneSelect } from "./AgentCronFields";
import "./AgentDraftForm.css";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { LoaderCircle, Square } from "lucide-react";
import { api, type Run } from "../api";
import { ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";
import LlamaModels from "./LlamaModels";
import { chatRequestId, clearChatRequest } from "./chat-draft";

const terminal = new Set(["succeeded", "failed", "canceled", "interrupted"]);

export default function AgentDraftForm() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const runId = params.get("draft_run") ?? "";
  const [instruction, setInstruction] = useState("");
  const [model, setModel] = useState("");
  const [zone, setZone] = useState(browserTimezone);
  const [modelBusy, setModelBusy] = useState(false);
  const restored = useRef("");
  const provider = useQuery({
    queryKey: ["chat-provider"],
    queryFn: () =>
      api<{ models: string[]; default_model: string }>("/chat/provider"),
  });
  const selectedModel = model || provider.data?.default_model || "";
  const current = useQuery({
    queryKey: ["agent-draft", runId],
    queryFn: () => api<Run>(`/agent-drafts/${runId}`),
    enabled: !!runId,
    refetchInterval: (query) =>
      terminal.has(query.state.data?.status ?? "") ? false : 1000,
  });
  const run = current.data;
  const active = !!runId && (!run || !terminal.has(run.status));
  useEffect(() => {
    if (!run) return;
    clearChatRequest("agent-factory");
    if (run.id !== restored.current) {
      restored.current = run.id;
      setInstruction(String(run.parameters.instruction ?? ""));
      setModel(String(run.parameters.model ?? ""));
    }
    const id = run.metadata?.agent_id;
    if (run.status === "succeeded" && typeof id === "string") {
      navigate(`/agents/${id}`, { replace: true });
    }
  }, [run, navigate]);
  const draft = useMutation({
    mutationFn: async () => {
      const body = {
        instruction: instruction.trim(),
        model: selectedModel,
        schedule_timezone: zone,
      };
      const key = await chatRequestId("agent-factory", JSON.stringify(body));
      return api<Run>("/agent-drafts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...body, client_request_id: key }),
      });
    },
    onSuccess: (result) => {
      setParams((previous) => {
        const next = new URLSearchParams(previous);
        next.set("draft_run", result.id);
        return next;
      });
    },
  });
  const quick = useMutation({
    mutationFn: () =>
      api<{ id: string }>("/agents/draft", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          instruction,
          model: selectedModel,
          schedule_timezone: zone,
        }),
      }),
    onSuccess: (agent) => navigate(`/agents/${agent.id}`),
  });
  const stop = useMutation({
    mutationFn: () =>
      api<Run>(`/agent-drafts/${runId}/cancel`, { method: "POST" }),
    onSuccess: () => current.refetch(),
  });
  const busy = active || draft.isPending || quick.isPending;
  const failure =
    run && ["failed", "interrupted"].includes(run.status)
      ? new Error(
          run.error_message ||
            "Preparation did not finish. Your instruction is kept below; try again or create without AI.",
        )
      : null;
  return (
    <form
      className="panel agent-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (!busy && !modelBusy && selectedModel && instruction.trim())
          draft.mutate();
      }}
    >
      <h2>Create an agent draft</h2>
      <p className="muted">
        Describe what you want done and how often. Your local model prepares the
        instructions, tools and schedule. Review them before enabling the agent.
      </p>
      <ScheduleTimezoneSelect value={zone} onChange={setZone} disabled={busy} />
      {runId && (
        <section
          className="panel agent-draft-progress"
          aria-label="Draft preparation"
        >
          <div className="agent-draft-progress-head">
            <p role="status">
              {active ? (
                <>
                  <LoaderCircle
                    size={16}
                    className="animate-spin"
                    aria-hidden="true"
                  />{" "}
                  Preparing your draft…
                </>
              ) : run?.status === "canceled" ? (
                "Preparation stopped. Your instruction is kept below."
              ) : failure ? (
                "The draft needs another attempt."
              ) : (
                "Draft preparation finished."
              )}
            </p>
            <Link to={`/runs/${runId}`}>Execution details</Link>
          </div>
          {active && (
            <Button
              type="button"
              variant="secondary"
              disabled={stop.isPending || run?.status === "cancel_requested"}
              onClick={() => stop.mutate()}
            >
              <Square size={14} />
              {run?.status === "cancel_requested"
                ? "Stopping…"
                : "Stop preparation"}
            </Button>
          )}
          <ErrorNotice error={current.error ?? stop.error ?? failure} />
          {current.isError && (
            <Button
              type="button"
              variant="secondary"
              disabled={current.isFetching}
              onClick={() => current.refetch()}
            >
              Check preparation again
            </Button>
          )}
        </section>
      )}
      <label>
        Instruction
        <textarea
          required
          maxLength={16000}
          rows={3}
          value={instruction}
          disabled={busy}
          onChange={(event) => setInstruction(event.target.value)}
          placeholder="Every morning find useful local AI updates and give me a short report with sources."
        />
      </label>
      <LlamaModels
        value={selectedModel}
        models={provider.data?.models ?? []}
        onSelect={setModel}
        onBusy={setModelBusy}
        busy={busy}
      />
      <ErrorNotice error={draft.error ?? quick.error ?? provider.error} />
      <div>
        <Button
          disabled={busy || modelBusy || !selectedModel || !instruction.trim()}
        >
          {draft.isPending || active
            ? "Preparing draft…"
            : failure || run?.status === "canceled"
              ? "Try again"
              : "Create draft"}
        </Button>
      </div>
      <details>
        <summary>Without AI</summary>
        <p className="muted">
          Create a quick draft from recognized keywords. Adjust its
          instructions, tools and schedule yourself.
        </p>
        <Button
          type="button"
          variant="secondary"
          disabled={busy || modelBusy || !instruction.trim()}
          onClick={() => quick.mutate()}
        >
          Create without AI
        </Button>
      </details>
    </form>
  );
}
