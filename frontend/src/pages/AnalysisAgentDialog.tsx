import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useMutation } from "@tanstack/react-query";
import { CalendarClock, X } from "lucide-react";
import { api } from "../api";
import { Button } from "../components/ui/button";
import { ErrorNotice } from "../components/common";
import { browserTimezone } from "./AgentCronFields";
import { chatRequestId, clearChatRequest } from "./chat-draft";
import "./AnalysisAgentDialog.css";

export type AnalysisAgentSource = {
  id: string;
  goal: string;
  liveSources: boolean;
};

export default function AnalysisAgentDialog({
  source,
  conversationId,
  settingsVersion,
  providerVersion,
  onClose,
  onCreated,
}: {
  source: AnalysisAgentSource;
  conversationId: string;
  settingsVersion: number;
  providerVersion?: string;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [schedule, setSchedule] = useState("Every morning at 09:00.");
  const [timezone] = useState(browserTimezone);
  const receiptKey = "analysis-agent:" + conversationId;
  const prepare = useMutation({
    mutationFn: async () => {
      const values = {
        conversation_id: conversationId,
        expected_settings_version: settingsVersion,
        ...(providerVersion
          ? { expected_provider_version: providerVersion }
          : {}),
        content:
          "Create an agent that repeats this analysis. " + schedule.trim(),
        action: "agent.create",
        execution_mode: "work",
        analysis_agent_source_run_id: source.id,
        schedule_timezone: timezone,
        web_search: { enabled: false, query: "" },
      };
      const id = await chatRequestId(receiptKey, JSON.stringify(values));
      return api("/chat/turns", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...values, client_request_id: id }),
      });
    },
    onSuccess: () => {
      clearChatRequest(receiptKey);
      onCreated();
    },
  });
  return (
    <Dialog.Root
      open
      onOpenChange={(open) => {
        if (!open && !prepare.isPending) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="chat-options-dialog analysis-agent-dialog">
          <div className="chat-drawer-heading">
            <Dialog.Title>Create an agent from this analysis</Dialog.Title>
            <Dialog.Close asChild>
              <Button
                variant="ghost"
                aria-label="Close agent creation"
                disabled={prepare.isPending}
              >
                <X size={18} />
              </Button>
            </Dialog.Close>
          </div>
          <Dialog.Description className="muted">
            Repeat this task on a schedule. Review the draft before enabling it.
          </Dialog.Description>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (schedule.trim() && !prepare.isPending) prepare.mutate();
            }}
          >
            <section
              className="analysis-agent-preview"
              aria-label="Selected analysis"
            >
              <strong>Task to repeat</strong>
              <p>
                {source.goal.slice(0, 600)}
                {source.goal.length > 600 ? "…" : ""}
              </p>
              <p className="muted">
                {source.liveSources
                  ? "Each run reads the same reviewed public sources again."
                  : "Each run uses the same selected saved files or captured data."}{" "}
                The agent has its own private workspace.
              </p>
            </section>
            <label>
              <span>
                <CalendarClock size={16} aria-hidden="true" /> When should it
                run?
              </span>
              <textarea
                value={schedule}
                maxLength={4000}
                rows={3}
                required
                disabled={prepare.isPending}
                onChange={(event) => setSchedule(event.target.value)}
                placeholder="For example: every weekday at 08:30"
              />
            </label>
            <p className="muted">
              Timezone: {timezone}. You can edit the proposed schedule before
              activation.
            </p>
            <ErrorNotice error={prepare.error} />
            <div className="row analysis-agent-actions">
              <Button
                type="button"
                variant="secondary"
                disabled={prepare.isPending}
                onClick={onClose}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={!schedule.trim() || prepare.isPending}
              >
                {prepare.isPending ? "Preparing…" : "Prepare draft"}
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
