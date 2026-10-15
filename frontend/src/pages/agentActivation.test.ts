import { expect, it } from "vitest";
import { activationBlock } from "./agentActivation";

const catalog = ["coding_local", "coding_cursor", "http_fetch"].map((name) => ({
  name,
  description: name,
  operational: true,
  required_permissions: [],
}));
it("allows a reviewed Local coding agent to use an automatic private workspace", () => {
  expect(
    activationBlock(
      {
        enabled: false,
        tools: ["coding_local"],
        model: "auto",
        project_id: null,
      },
      catalog,
    ),
  ).toEqual({ blocked: false, reason: null });
  expect(
    activationBlock(
      {
        enabled: false,
        tools: ["coding_local", "http_fetch"],
        model: "auto",
        fetch_urls: ["https://example.com/"],
      },
      catalog,
    ).blocked,
  ).toBe(false);
});
it("retains explicit project, external permission and public URL requirements", () => {
  expect(
    activationBlock(
      {
        enabled: false,
        tools: ["coding_cursor"],
        permission_profile: "agent_external_coding",
      },
      catalog,
    ).reason,
  ).toMatch(/Choose the project/);
  expect(
    activationBlock(
      { enabled: false, tools: ["coding_cursor"], project_id: "repo" },
      catalog,
    ).reason,
  ).toMatch(/external-coding permission/);
  expect(
    activationBlock(
      { enabled: false, tools: ["coding_local", "http_fetch"], model: "auto" },
      catalog,
    ).reason,
  ).toMatch(/reviewed public URLs/);
});
