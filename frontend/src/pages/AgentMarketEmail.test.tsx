import type { Run } from "../api";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import type { ReactElement } from "react";
import {
  AgentMarketRunStop,
  MarketEmailApproval,
  MarketEmailSettings,
} from "./AgentMarketEmail";
import { DEFAULT_MARKET } from "./marketScope";
import { agentSettingsPayload } from "./agentSettings";

const connection = {
  id: "mail-one",
  name: "My email",
  kind: "email",
  enabled: true,
  email_policy_revision: "a".repeat(64),
  smtp: {
    sender: "station@example.com",
    allowed_recipients: ["one@example.com", "two@example.com"],
  },
};
const market = {
  ...DEFAULT_MARKET,
  email: {
    connector_id: connection.id,
    connector_revision: connection.email_policy_revision,
    recipients: ["one@example.com"],
  },
};
beforeEach(() =>
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, json: async () => [connection] })),
  ),
);
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function mount(element: ReactElement) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>{element}</MemoryRouter>
    </QueryClientProvider>,
  );
}

it("selects an account and allowed recipient without sending or granting consent", async () => {
  const change = vi.fn();
  mount(<MarketEmailSettings value={DEFAULT_MARKET} onChange={change} />);
  await screen.findByRole("option", { name: "AI Station + email · My email" });
  fireEvent.change(screen.getByLabelText("Deliver alerts to"), {
    target: { value: connection.id },
  });
  expect(change).toHaveBeenCalledWith(market);
  expect(vi.mocked(fetch).mock.calls.every((call) => !call[1]?.method)).toBe(
    true,
  );
});

it("requires unchecked consent after disclosing sender, recipients and threshold", async () => {
  const change = vi.fn(),
    ready = vi.fn();
  mount(
    <MarketEmailApproval
      market={market}
      enabled={false}
      checked={false}
      onChange={change}
      onReadyChange={ready}
    />,
  );
  const checkbox = await screen.findByRole("checkbox", {
    name: /I allow this agent/,
  });
  await waitFor(() => expect(checkbox.matches(":disabled")).toBe(false));
  expect((checkbox as HTMLInputElement).checked).toBe(false);
  expect(screen.getByText("station@example.com")).toBeTruthy();
  expect(screen.getByText("one@example.com")).toBeTruthy();
  expect(screen.getByText(/change reaches 5%/)).toBeTruthy();
  expect(change).not.toHaveBeenCalled();
  fireEvent.click(checkbox);
  expect(change).toHaveBeenCalledWith(true);
  expect(ready).toHaveBeenLastCalledWith(true);
});

it("disables consent when the saved connector revision changes", async () => {
  const change = vi.fn();
  mount(
    <MarketEmailApproval
      market={{
        ...market,
        email: { ...market.email, connector_revision: "b".repeat(64) },
      }}
      enabled={false}
      checked={true}
      onChange={change}
      onReadyChange={vi.fn()}
    />,
  );
  await screen.findByText(/Review the saved mail connection/);
  const checkbox = screen.getByRole("checkbox", {
    name: /I allow this agent/,
  }) as HTMLInputElement;
  expect(checkbox.disabled).toBe(true);
  expect(checkbox.checked).toBe(false);
  expect(change).not.toHaveBeenCalled();
});

it("requires an explicit scope update after mail settings change", async () => {
  const change = vi.fn();
  mount(
    <MarketEmailSettings
      value={{
        ...market,
        email: { ...market.email, connector_revision: "b".repeat(64) },
      }}
      onChange={change}
    />,
  );
  const button = await screen.findByRole("button", {
    name: "Use current mail settings",
  });
  expect(change).not.toHaveBeenCalled();
  fireEvent.click(button);
  expect(change).toHaveBeenCalledWith(market);
});

it("pauses changed price/email policies while preserving enablement for unrelated edits", () => {
  const agent = {
    name: "Watch",
    updated_at: "now",
    tools: ["market_watch"],
    enabled: true,
    market,
  };
  expect(agentSettingsPayload(agent, { description: "Updated" }).enabled).toBe(
    true,
  );
  const next = agentSettingsPayload(agent, {
    market: { ...market, threshold_percent: "6" },
  });
  expect(next.enabled).toBe(false);
  expect(next.market?.email).toEqual(market.email);
});

it("stops the workflow dispatch when its nested mail is still queued", async () => {
  const runs = [
    {
      id: "workflow-one",
      task_id: "task-one",
      executor_type: "agent_workflow",
      status: "succeeded",
    },
    {
      id: "mail-run",
      task_id: "task-one",
      executor_type: "email_send",
      status: "queued",
    },
  ] as Run[];
  mount(<AgentMarketRunStop agentId="agent-one" runs={runs} />);
  expect(vi.mocked(fetch)).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "Stop current price check" }),
  );
  await waitFor(() =>
    expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      "/api/runs/workflow-one/cancel",
      { method: "POST" },
    ),
  );
});
