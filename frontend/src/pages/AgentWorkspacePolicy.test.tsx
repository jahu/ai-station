import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import AgentWorkspacePolicy from "./AgentWorkspacePolicy";
import { agentSettingsPayload } from "./agentSettings";

afterEach(cleanup);
it("reviews public dependency downloads and detected builds before workspace creation", () => {
  const change = vi.fn();
  render(<AgentWorkspacePolicy onChange={change} />);
  const install = screen.getByRole("checkbox", {
    name: "Install declared project dependencies",
  });
  expect((install as HTMLInputElement).checked).toBe(false);
  expect(screen.getByText(/checked public package sources/)).toBeTruthy();
  expect(change).not.toHaveBeenCalled();
  fireEvent.click(install);
  expect(change).toHaveBeenCalledWith({
    auto_install_dependencies: true,
    auto_validate: false,
  });
});
it("keeps an existing project's saved policy authoritative", () => {
  const change = vi.fn();
  render(
    <AgentWorkspacePolicy
      value={{ auto_install_dependencies: true, auto_validate: true }}
      linkedProject="existing-project"
      onChange={change}
    />,
  );
  const fieldset = screen.getByRole("group", {
    name: "Build and check the result",
  }) as HTMLFieldSetElement;
  expect(fieldset.disabled).toBe(true);
  expect(
    screen.getByText(/linked project's saved dependency and validation policy/),
  ).toBeTruthy();
  expect(change).not.toHaveBeenCalled();
});
it("retains reviewed policy on ordinary definition edits and clears it when changing tool scope", () => {
  const source = {
    updated_at: "revision",
    name: "Builder",
    tools: ["coding_local"],
    workspace_policy: { auto_install_dependencies: true, auto_validate: true },
  };
  expect(
    agentSettingsPayload(source, { goal: "Build a site" }).workspace_policy,
  ).toEqual(source.workspace_policy);
  expect(
    agentSettingsPayload(source, { tools: ["system_snapshot"] })
      .workspace_policy,
  ).toEqual({});
  expect(
    agentSettingsPayload({ updated_at: "revision", name: "Legacy" })
      .workspace_policy,
  ).toBeUndefined();
});
