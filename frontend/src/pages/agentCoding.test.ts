import { expect, it } from "vitest";
import { activationBlock } from "./agentActivation";
const tools = [
  {
    name: "coding_local",
    description: "Build in an isolated worktree",
    operational: true,
    required_permissions: ["workspace_write"],
  },
];
it("allows Local coding activation with an automatic workspace or an explicit project", () => {
  const agent = { enabled: false, model: "local", tools: ["coding_local"] };
  expect(activationBlock(agent, tools).blocked).toBe(false);
  expect(
    activationBlock({ ...agent, project_id: "project" }, tools).blocked,
  ).toBe(false);
});
it("does not silently combine coding writes with report tools", () => {
  expect(
    activationBlock(
      {
        enabled: false,
        model: "local",
        project_id: "project",
        tools: ["coding_local", "system_snapshot"],
      },
      tools,
    ).reason,
  ).toMatch(/select Local coding alone/i);
});
