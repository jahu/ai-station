import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { AgentProjectList } from "./AgentProjectList";

afterEach(cleanup);
it("explains the automatic workspace and only saves an explicitly chosen association", () => {
  const save = vi.fn();
  render(
    <AgentProjectList
      agentId="builder"
      projectId="existing"
      projects={[{ id: "existing", name: "My project" }]}
      automaticWorkspace
      onSave={save}
    />,
  );
  expect(
    screen.getByText(/creates a private workspace on the first Run/),
  ).toBeTruthy();
  expect(
    screen.getByText("Create a private workspace automatically"),
  ).toBeTruthy();
  expect(save).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("radio", { name: "Linked project none builder" }),
  );
  expect(save).toHaveBeenCalledExactlyOnceWith(null);
});
