import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";

type AgentDraft = {
  id: string;
  name: string;
  model: string;
  enabled: boolean;
  updated_at: string;
};

export function AssistantAgentDraft({
  agentId,
  tabIndex = 0,
}: {
  agentId: string;
  tabIndex?: number;
}) {
  const cache = useQueryClient();
  const shortId = agentId.slice(0, 8);
  const detail = useQuery({
    queryKey: ["agent", agentId],
    queryFn: () => api<AgentDraft>(`/agents/${agentId}`),
  });
  const toggle = useMutation({
    mutationFn: (enabled: boolean) =>
      api<AgentDraft>(`/agents/${agentId}/enabled`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_updated_at: detail.data!.updated_at,
          enabled,
        }),
      }),
    onSuccess: (result) => {
      cache.setQueryData(["agent", agentId], result);
      void cache.invalidateQueries({ queryKey: ["agents"] });
    },
  });
  const agent = detail.data;
  const enableLabel = agent?.enabled
    ? `Pause agent ${shortId}`
    : `Enable saved definition ${shortId}`;
  return (
    <div className="assistant-agent-draft">
      <ErrorNotice error={detail.error ?? toggle.error} />
      {agent && (
        <>
          <p>
            <strong>{agent.name}</strong>
            {agent.enabled ? " · Enabled" : " · Disabled draft"}
            {agent.model ? ` · ${agent.model}` : ""}
          </p>
          <p className="muted">
            Activation stays explicit and uses the saved definition. It does not
            invent a conversation Run.
          </p>
          <div className="row">
            <Button
              type="button"
              disabled={toggle.isPending}
              tabIndex={tabIndex}
              aria-label={enableLabel}
              onClick={() => toggle.mutate(!agent.enabled)}
            >
              {agent.enabled ? "Pause agent" : "Enable saved definition"}
            </Button>
            <Button asChild variant="secondary">
              <Link
                to={`/agents/${agentId}`}
                tabIndex={tabIndex}
                aria-label={`Review agent ${shortId}`}
              >
                Open in Agents
              </Link>
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
