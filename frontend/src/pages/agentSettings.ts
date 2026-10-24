import { DEFAULT_MARKET, type MarketScope } from "./marketScope";
import type { ResultEmailScope } from "./AgentResultEmail";
import type { AgentMediaScope } from "./agent-media";
export type AgentSettingsInput = {
  updated_at: string;
  name: string;
  description?: string;
  goal?: string;
  system_prompt?: string;
  model?: string | null;
  tools?: string[];
  workspace_policy?: {
    auto_install_dependencies?: boolean;
    auto_validate?: boolean;
  };
  market?: MarketScope | null;
  data?: {
    input_artifact_ids: string[];
    max_repairs: number;
    operation?: "analyze" | "create";
  } | null;
  media?: AgentMediaScope | null;
  permission_profile?: "agent_local" | "agent_external_coding";
  search_query?: string | null;
  fetch_urls?: string[] | null;
  skills?: string[];
  trigger?: string;
  cron_expr?: string | null;
  schedule_timezone?: string;
  interval_seconds?: number | null;
  run_at?: string | null;
  maximum_runtime?: number;
  output_expectation?: string;
  require_approval?: boolean;
  workflow_mode?: string;
  tool_calling?: boolean | string;
  retry_policy?: { mode?: string };
  notification_policy?: {
    on_success?: boolean;
    on_failure?: boolean;
    on_approval?: boolean;
    report_email?: ResultEmailScope | null;
  };
  github?: { connector_id: string; repository: string } | null;
  http?: { connector_id: string; connector_revision: string } | null;
  project_id?: string | null;
  enabled?: boolean;
};

export function agentSettingsPayload(
  agent: AgentSettingsInput,
  patch: Partial<AgentSettingsInput> = {},
) {
  const next = {
    ...agent,
    ...patch,
    notification_policy: {
      ...agent.notification_policy,
      ...patch.notification_policy,
    },
  };
  const trigger = next.trigger ?? "manual";
  return {
    expected_updated_at: next.updated_at,
    name: next.name,
    description: next.description ?? "",
    goal: next.goal ?? "",
    system_prompt: next.system_prompt ?? "",
    model: next.model ?? "",
    tools: next.tools ?? [],
    ...(next.market !== undefined || next.tools?.includes("market_watch")
      ? {
          market: next.tools?.includes("market_watch")
            ? (next.market ?? DEFAULT_MARKET)
            : null,
        }
      : {}),
    ...(next.workspace_policy !== undefined
      ? {
          workspace_policy: next.tools?.includes("coding_local")
            ? next.workspace_policy
            : {},
        }
      : {}),
    ...(next.data !== undefined ? { data: next.data } : {}),
    ...(next.media !== undefined
      ? { media: next.tools?.includes("create_media") ? next.media : null }
      : {}),
    ...(next.permission_profile !== undefined
      ? { permission_profile: next.permission_profile }
      : {}),
    ...(next.github !== undefined ? { github: next.github } : {}),
    ...(next.http !== undefined
      ? { http: next.tools?.includes("http_connector") ? next.http : null }
      : {}),
    search_query: next.search_query ?? "",
    fetch_urls: next.fetch_urls ?? [],
    skills: next.skills ?? [],
    trigger,
    cron_expr: trigger === "cron" ? (next.cron_expr ?? "") : "",
    schedule_timezone: next.schedule_timezone ?? "UTC",
    interval_seconds:
      trigger === "interval" ? (next.interval_seconds ?? 3600) : null,
    run_at: trigger === "datetime" ? (next.run_at ?? null) : null,
    maximum_runtime: next.maximum_runtime ?? 600,
    output_expectation: next.output_expectation ?? "A concise, factual report.",
    require_approval: next.require_approval ?? false,
    workflow_mode: next.workflow_mode === "gated" ? "gated" : "sequential",
    tool_calling:
      next.tool_calling === true || next.tool_calling === "bounded"
        ? "bounded"
        : "none",
    retry_policy: {
      mode: next.retry_policy?.mode === "manual" ? "manual" : "none",
    },
    notification_policy: {
      on_success: next.notification_policy?.on_success === true,
      on_failure: next.notification_policy?.on_failure === true,
      on_approval: next.notification_policy?.on_approval === true,
      ...(next.notification_policy?.report_email !== undefined
        ? { report_email: next.notification_policy.report_email }
        : {}),
    },
    project_id: next.project_id ?? null,
    enabled:
      (next.enabled ?? false) &&
      (patch.market === undefined ||
        JSON.stringify(patch.market) === JSON.stringify(agent.market)),
  };
}

export function resultEmailConsentKey(agent: {
  id: string;
  updated_at: string;
}) {
  return `${agent.id}:${agent.updated_at}`;
}
