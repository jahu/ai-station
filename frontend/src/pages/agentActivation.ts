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

export function activationBlock(
  agent: {
    enabled: boolean;
    model?: string | null;
    tools?: string[];
    search_query?: string | null;
    fetch_urls?: string[] | null;
  },
  catalog: unknown,
): { blocked: boolean; reason: string | null } {
  if (agent.enabled) return { blocked: false, reason: null };
  if (!(agent.model ?? "").trim()) {
    return {
      blocked: true,
      reason: "Select a local model before enabling.",
    };
  }
  const names = agent.tools ?? [];
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
  if (!blocked.length) return { blocked: false, reason: null };
  return {
    blocked: true,
    reason: `Unavailable tools prevent activation: ${blocked.join(", ")}.`,
  };
}
