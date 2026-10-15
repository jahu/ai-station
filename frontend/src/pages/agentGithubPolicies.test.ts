import { expect, it } from "vitest";
import { activationBlock } from "./agentActivation";
import { agentSettingsPayload } from "./agentSettings";

const catalog = [
  {
    name: "github_read",
    description: "Read selected repository",
    operational: true,
    required_permissions: ["github_read", "network_read"],
  },
];
const github = { connector_id: "repo-id", repository: "owner/repo" };
it("requires reviewed scope and a runtime budget before enabling GitHub reads", () => {
  const agent = { enabled: false, model: "local", tools: ["github_read"] };
  expect(activationBlock(agent, catalog).blocked).toBe(true);
  expect(
    activationBlock({ ...agent, github, maximum_runtime: 69 }, catalog).blocked,
  ).toBe(true);
  expect(
    activationBlock({ ...agent, github, maximum_runtime: 70 }, catalog).blocked,
  ).toBe(false);
});
it("saves the exact reviewed scope and preserves legacy payloads without it", () => {
  const agent = {
    updated_at: "2026-10-15T12:00:00Z",
    name: "Repository report",
    goal: "Read repo",
  };
  expect(agentSettingsPayload({ ...agent, github }).github).toEqual(github);
  expect(agentSettingsPayload(agent)).not.toHaveProperty("github");
});
