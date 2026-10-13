import { describe, expect, it } from "vitest";
import { activationBlock } from "./agentActivation";

const catalog = [
  {
    name: "project_memory",
    description: "Read only the linked project",
    operational: true,
    required_permissions: ["project_memory_read"],
  },
];
const agent = { enabled: false, model: "local", tools: ["project_memory"] };

describe("explicit project memory access", () => {
  it("requires the reviewed project before activation", () => {
    expect(activationBlock(agent, catalog).blocked).toBe(true);
    expect(activationBlock(agent, catalog).reason).toMatch(/whose memory/);
    expect(
      activationBlock({ ...agent, project_id: "project-one" }, catalog),
    ).toEqual({ blocked: false, reason: null });
  });
  it("keeps project links independent of memory selection", () => {
    expect(
      activationBlock(
        { ...agent, tools: [], project_id: "project-one" },
        catalog,
      ),
    ).toEqual({ blocked: false, reason: null });
    expect(
      activationBlock({ ...agent, project_id: "project-one" }, []).blocked,
    ).toBe(true);
  });
});
