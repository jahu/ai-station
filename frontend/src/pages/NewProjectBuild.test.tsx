import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { NewProjectBuild } from "./NewProjectBuild";
import { newProjectScope } from "./new-project-scope";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("chooses a project name and provider, clearing stale sharing consent on switch", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({
        models: [{ id: "test-model", name: "Test model" }],
      }),
    })),
  );
  function Composer() {
    const [scope, setScope] = useState(newProjectScope);
    return (
      <>
        <NewProjectBuild value={scope} onChange={setScope} />
        <output data-testid="scope">{JSON.stringify(scope)}</output>
      </>
    );
  }
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Composer />
    </QueryClientProvider>,
  );
  fireEvent.change(screen.getByRole("textbox", { name: "Project name" }), {
    target: { value: "Weather Station" },
  });
  expect(
    (screen.getByRole("radio", { name: "Local AI" }) as HTMLInputElement)
      .checked,
  ).toBe(true);
  fireEvent.click(screen.getByRole("radio", { name: "Cursor" }));
  fireEvent.click(screen.getByText("Model · Auto"));
  await screen.findByRole("radio", { name: /Test model/ });
  fireEvent.click(screen.getByRole("radio", { name: /Test model/ }));
  fireEvent.click(screen.getByRole("checkbox", { name: /Allow sharing/ }));
  expect(JSON.parse(screen.getByTestId("scope").textContent!).external_ai).toBe(
    true,
  );
  fireEvent.click(screen.getByRole("radio", { name: "Codex" }));
  let scope = JSON.parse(screen.getByTestId("scope").textContent!);
  expect(scope).toMatchObject({
    name: "Weather Station",
    executor: "codex",
    model: "",
    external_ai: false,
  });
  fireEvent.click(screen.getByRole("radio", { name: "Local AI" }));
  scope = JSON.parse(screen.getByTestId("scope").textContent!);
  expect(scope.external_ai).toBe(false);
  expect(screen.queryByRole("checkbox", { name: /Allow sharing/ })).toBeNull();
});
