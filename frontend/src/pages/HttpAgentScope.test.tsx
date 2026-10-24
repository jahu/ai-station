import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import HttpAgentScope from "./HttpAgentScope";
import { activationBlock } from "./agentActivation";
import { agentSettingsPayload } from "./agentSettings";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const revision = "a".repeat(64);
const scope = { connector_id: "api-id", connector_revision: revision };
function show(value: typeof scope | null, disabled = false) {
  const onChange = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => [
        {
          id: "api-id",
          name: "Prices",
          kind: "http",
          enabled: true,
          url: "https://data.example.com/values",
          http_policy_revision: revision,
          secret_source: "stored",
          secret_present: true,
        },
        { id: "off", name: "Disabled", kind: "http", enabled: false },
        { id: "github", name: "Repository", kind: "github", enabled: true },
      ],
    })),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <HttpAgentScope value={value} disabled={disabled} onChange={onChange} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return onChange;
}
it("selects only the fixed reviewed scope without running or exposing credentials", async () => {
  const change = show(null);
  await screen.findByRole("option", { name: /Prices/ });
  expect(change).not.toHaveBeenCalled();
  expect(
    screen.queryByRole("option", { name: /Disabled|Repository/ }),
  ).toBeNull();
  fireEvent.change(
    screen.getByRole("combobox", { name: "Reviewed HTTP connection" }),
    { target: { value: "api-id" } },
  );
  expect(change).toHaveBeenCalledWith(scope);
});
it("shows address and server-side credential use for the saved selection", async () => {
  show(scope);
  await screen.findByText(/Saved credential/);
  expect(screen.getByLabelText("Reviewed API address").textContent).toContain(
    "https://data.example.com/values",
  );
  expect(
    screen
      .getByRole("link", { name: "Manage API connections" })
      .getAttribute("href"),
  ).toBe("/settings/integrations");
});
it("does not silently adopt a changed policy and respects execution lock", async () => {
  const change = show({ ...scope, connector_revision: "b".repeat(64) }, true);
  await screen.findByRole("status");
  const select = screen.getByRole("combobox", {
    name: "Reviewed HTTP connection",
  }) as HTMLSelectElement;
  expect(select.value).toBe("");
  expect(select.disabled).toBe(true);
  expect(change).not.toHaveBeenCalled();
});
it("blocks activation until reviewed and clears removed tool scope in saved payload", () => {
  const agent = {
    updated_at: "now",
    name: "API analyst",
    enabled: false,
    model: "local",
    tools: ["http_connector"],
  };
  const tools = [
    {
      name: "http_connector",
      description: "",
      operational: true,
      required_permissions: ["network_read", "http_connector_read"],
    },
  ];
  expect(activationBlock(agent, tools).blocked).toBe(true);
  expect(activationBlock({ ...agent, http: scope }, tools).blocked).toBe(false);
  expect(agentSettingsPayload({ ...agent, http: scope }).http).toEqual(scope);
  expect(
    agentSettingsPayload({ ...agent, http: scope }, { tools: [] }).http,
  ).toBeNull();
  expect(agentSettingsPayload(agent)).not.toHaveProperty("http");
  expect(
    activationBlock(
      {
        ...agent,
        tools: ["python_data", "http_connector"],
        model: "auto",
        data_readiness: { ready: true, reason: "" },
        http: scope,
        data: { input_artifact_ids: [], max_repairs: 1 },
      },
      [
        ...tools,
        {
          name: "python_data",
          description: "",
          operational: true,
          required_permissions: [],
        },
      ],
    ).blocked,
  ).toBe(false);
});
