import { expect, it } from "vitest";
import { activationBlock } from "./agentActivation";
const catalog = ["coding_local", "coding_cursor", "coding_codex"].map(
  (name) => ({
    name,
    description: name,
    operational: true,
    required_permissions: [],
  }),
);
it("allows Local coding with reviewed pages and blocks missing URLs or external sharing", () => {
  const tools = [
    ...catalog,
    {
      name: "http_fetch",
      description: "Reviewed pages",
      operational: true,
      required_permissions: ["network_read"],
    },
  ];
  const agent = {
    enabled: false,
    model: "auto",
    tools: ["coding_local", "http_fetch"],
    project_id: "project",
    fetch_urls: ["https://example.com/"],
  };
  expect(activationBlock(agent, tools)).toEqual({
    blocked: false,
    reason: null,
  });
  expect(activationBlock({ ...agent, fetch_urls: [] }, tools).blocked).toBe(
    true,
  );
  expect(
    activationBlock(
      {
        ...agent,
        tools: ["coding_cursor", "http_fetch"],
        permission_profile: "agent_external_coding",
      },
      tools,
    ).blocked,
  ).toBe(true);
});
it("enables a reviewed external coding scope without selecting a local model", () => {
  for (const tool of ["coding_cursor", "coding_codex"]) {
    expect(
      activationBlock(
        {
          enabled: false,
          model: "",
          tools: [tool],
          project_id: "project",
          permission_profile: "agent_external_coding",
        },
        catalog,
      ),
    ).toEqual({ blocked: false, reason: null });
  }
});
it("blocks an unreviewed external permission profile", () => {
  expect(
    activationBlock(
      {
        enabled: false,
        model: "local",
        tools: ["coding_cursor"],
        project_id: "project",
      },
      catalog,
    ).blocked,
  ).toBe(true);
});
it("requires a single linked coding scope before enabling", () => {
  for (const patch of [
    { project_id: null },
    { tools: ["coding_cursor", "coding_codex"] },
  ]) {
    expect(
      activationBlock(
        {
          enabled: false,
          model: "",
          tools: ["coding_cursor"],
          project_id: "project",
          permission_profile: "agent_external_coding",
          ...patch,
        },
        catalog,
      ).blocked,
    ).toBe(true);
  }
});
it("continues to require a local model for Local coding", () => {
  expect(
    activationBlock(
      {
        enabled: false,
        model: "",
        tools: ["coding_local"],
        project_id: "project",
      },
      catalog,
    ).reason,
  ).toMatch(/local model/);
});

it("allows reviewed research before local code, with separate query and source requirements", () => {
  const tools = [
    ...catalog,
    ...["web_search", "search_pages", "http_fetch"].map((name) => ({
      name,
      description: name,
      operational: true,
      required_permissions: ["network_read"],
    })),
  ];
  const agent = {
    enabled: false,
    model: "auto",
    tools: ["coding_local", "web_search", "search_pages"],
    search_query: "public release notes",
  };
  expect(activationBlock(agent, tools)).toEqual({
    blocked: false,
    reason: null,
  });
  expect(activationBlock({ ...agent, search_query: "" }, tools).reason).toMatch(
    /public search query/,
  );
  expect(
    activationBlock(
      { ...agent, tools: ["coding_local", "search_pages"] },
      tools,
    ).reason,
  ).toMatch(/requires web_search/);
  expect(
    activationBlock({ ...agent, tools: [...agent.tools, "http_fetch"] }, tools)
      .reason,
  ).toMatch(/reviewed public URLs/);
  expect(
    activationBlock(
      {
        ...agent,
        tools: [...agent.tools, "http_fetch"],
        fetch_urls: ["https://example.com/"],
      },
      tools,
    ).blocked,
  ).toBe(false);
});
