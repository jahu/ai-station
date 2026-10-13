export type AgentToolSpec = {
  name: string;
  description: string;
  operational: boolean;
  required_permissions: string[];
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
    project_id?: string | null;
    model?: string | null;
    tools?: string[];
    skills?: string[];
    search_query?: string | null;
    fetch_urls?: string[] | null;
  },
  catalog: unknown,
  skillsCatalog?: unknown,
): { blocked: boolean; reason: string | null } {
  if (agent.enabled) return { blocked: false, reason: null };
  if (!(agent.model ?? "").trim()) {
    return {
      blocked: true,
      reason: "Select a local model before enabling.",
    };
  }
  const names = agent.tools ?? [];
  if (names.includes("project_memory") && !agent.project_id) {
    return {
      blocked: true,
      reason:
        "Choose the project whose memory this agent may read before enabling.",
    };
  }
  if (names.includes("coding_local") && !agent.project_id) {
    return {
      blocked: true,
      reason:
        "Choose the project this coding agent may modify before enabling.",
    };
  }
  if (names.includes("coding_local") && names.length !== 1) {
    return {
      blocked: true,
      reason:
        "Select Local coding alone; reporting tools belong to a separate agent.",
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
