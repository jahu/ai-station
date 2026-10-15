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
