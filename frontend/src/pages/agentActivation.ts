import {
  agentMediaIssue,
  fixedAgentMedia,
  type AgentMediaScope,
} from "./agent-media";
import type { MarketScope } from "./marketScope";
export type AgentToolSpec = {
  name: string;
  description: string;
  operational: boolean;
  required_permissions: string[];
  outputs?: Partial<
    Record<
      AgentMediaScope["kind"],
      {
        ready: boolean;
        speech_ready?: boolean;
        reason?: string | null;
        modes?: string[];
      }
    >
  >;
};

export function isAgentToolList(value: unknown): value is AgentToolSpec[] {
  return (
    Array.isArray(value) &&
    value.every(
      (item) =>
        item &&
        typeof item === "object" &&
        typeof item.name === "string" &&
        typeof item.description === "string" &&
        typeof item.operational === "boolean" &&
        Array.isArray(item.required_permissions),
    )
  );
}

export function isAgentSkillList(value: unknown): value is { id: string }[] {
  return (
    Array.isArray(value) &&
    value.every(
      (item) => item && typeof item === "object" && typeof item.id === "string",
    )
  );
}

export function activationBlock(
  agent: {
    enabled: boolean;
    market?: MarketScope | null;
    market_readiness?: { ready: boolean; reason: string | null } | null;
    github?: { connector_id: string; repository: string } | null;
    maximum_runtime?: number;
    project_id?: string | null;
    model?: string | null;
    permission_profile?: string;
    tools?: string[];
    data?: { input_artifact_ids: string[]; max_repairs: number } | null;
    media?: AgentMediaScope | null;
    data_readiness?: { ready: boolean; reason: string } | null;
    skills?: string[];
    search_query?: string | null;
    fetch_urls?: string[] | null;
  },
  catalog: unknown,
  skillsCatalog?: unknown,
): { blocked: boolean; reason: string | null } {
  if (agent.enabled) return { blocked: false, reason: null };
  const names = agent.tools ?? [];
  const market = names.includes("market_watch");
  if (market && (names.length !== 1 || !agent.market?.instruments.length))
    return {
      blocked: true,
      reason:
        "Review and save an exclusive price-watch policy before enabling.",
    };
  if (market && agent.market?.provider === "finnhub" && !agent.market.feed)
    return {
      blocked: true,
      reason: "Review and save a stock-data account before enabling.",
    };
  if (market && agent.market_readiness?.ready === false)
    return {
      blocked: true,
      reason: agent.market_readiness.reason ?? "Review the stock-data account.",
    };
  const coding = names.filter((name) =>
    ["coding_local", "coding_cursor", "coding_codex"].includes(name),
  );
  if (names.includes("python_data")) {
    if (
      names.length !== 1 ||
      !agent.data?.input_artifact_ids.length ||
      !agent.data_readiness?.ready
    )
      return {
        blocked: true,
        reason:
          agent.data_readiness?.reason ||
          "Choose CSV/Excel inputs, wait for inspection and save the definition.",
      };
    if (agent.model !== "auto" && !agent.model?.startsWith("llamacpp:"))
      return {
        blocked: true,
        reason:
          "Choose Auto or an installed llama.cpp model for data analysis.",
      };
  }
  const external = coding.some((name) => name !== "coding_local");
  if (external !== (agent.permission_profile === "agent_external_coding")) {
    return {
      blocked: true,
      reason:
        "Review and save the explicit external-coding permission profile before enabling.",
    };
  }
  if (names.includes("create_media")) {
    const issue = agentMediaIssue(agent.media);
    if (issue) return { blocked: true, reason: issue };
    if (agent.media?.description_source === "fixed" && !fixedAgentMedia(agent))
      return {
        blocked: true,
        reason: "Use a goal-based description with research tools.",
      };
  }
  if (
    !external &&
    !market &&
    !fixedAgentMedia(agent) &&
    !(agent.model ?? "").trim()
  ) {
    return {
      blocked: true,
      reason: "Select a local model before enabling.",
    };
  }
  if (
    names.includes("github_read") &&
    (!agent.github || (agent.maximum_runtime ?? 600) < 70)
  ) {
    return {
      blocked: true,
      reason:
        "Choose a GitHub repository and at least 70 seconds runtime before enabling.",
    };
  }
  if (names.includes("project_memory") && !agent.project_id) {
    return {
      blocked: true,
      reason:
        "Choose the project whose memory this agent may read before enabling.",
    };
  }
  if (external && !agent.project_id) {
    return {
      blocked: true,
      reason:
        "Choose the project this coding agent may modify before enabling.",
    };
  }
  const localPages =
    coding.length === 1 &&
    coding[0] === "coding_local" &&
    names.every((name) => ["coding_local", "http_fetch"].includes(name));
  if (coding.length && names.length !== 1 && !localPages) {
    return {
      blocked: true,
      reason: external
        ? "Select one coding provider alone; reporting tools belong to a separate agent."
        : "Select Local coding alone; reporting tools belong to a separate agent.",
    };
  }
  if (names.includes("web_search") && !(agent.search_query ?? "").trim()) {
    return {
      blocked: true,
      reason: "web_search needs a public search query before activation.",
    };
  }
  if (names.includes("http_fetch") && !agent.fetch_urls?.length) {
    return {
      blocked: true,
      reason: "http_fetch needs reviewed public URLs before activation.",
    };
  }
  const skillIds = agent.skills ?? [];
  if (skillIds.length) {
    if (skillsCatalog == null) return { blocked: true, reason: null };
    if (!isAgentSkillList(skillsCatalog)) {
      return {
        blocked: true,
        reason: "Missing skills prevent activation.",
      };
    }
    const byId = new Map(skillsCatalog.map((skill) => [skill.id, skill]));
    const missing = skillIds.filter((id) => !byId.has(id));
    if (missing.length) {
      return {
        blocked: true,
        reason: `Missing skills prevent activation: ${missing.join(", ")}.`,
      };
    }
  }
  if (!names.length) return { blocked: false, reason: null };
  if (catalog == null) return { blocked: true, reason: null };
  if (!isAgentToolList(catalog)) {
    return {
      blocked: true,
      reason: "Unavailable tools prevent activation.",
    };
  }
  const byName = new Map(catalog.map((tool) => [tool.name, tool]));
  if (names.includes("create_media") && agent.media) {
    const output = byName.get("create_media")?.outputs?.[agent.media.kind];
    if (
      agent.media.kind === "avatar" &&
      agent.media.request.speech_text !== null &&
      output?.speech_ready === false
    )
      return {
        blocked: true,
        reason:
          "Polish speech is unavailable; review Audio setup or choose a saved recording.",
      };
    if (
      output &&
      (!output.ready ||
        (agent.media.kind === "image" &&
          output.modes &&
          !output.modes.includes(agent.media.request.mode)))
    )
      return {
        blocked: true,
        reason:
          output.reason || "The selected local media engine is unavailable.",
      };
  }
  const blocked = names.filter((name) => {
    const tool = byName.get(name);
    return !tool || !tool.operational;
  });
  if (!blocked.length) {
    if (names.includes("browser") && !agent.fetch_urls?.length) {
      return {
        blocked: true,
        reason: "Browser needs reviewed public URLs before activation.",
      };
    }
    return { blocked: false, reason: null };
  }
  return {
    blocked: true,
    reason: `Unavailable tools prevent activation: ${blocked.join(", ")}.`,
  };
}
