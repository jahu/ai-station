import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { AssistantAgentDraft } from "./AssistantAgentDraft";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const draft = {
  id: "agent-one",
  name: "Morning briefing",
  model: "local-27b",
  enabled: false,
  updated_at: "2026-10-11T10:00:00Z",
};

function mount(agent = draft) {
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      String(path).endsWith("/enabled")
        ? { ...agent, enabled: true, updated_at: "2026-10-11T10:01:00Z" }
        : agent,
  }));
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <AssistantAgentDraft agentId={agent.id} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return fetch;
}

it("enables a disabled draft from the conversation without inventing a Run", async () => {
  const fetch = mount();
  expect(await screen.findByText("Morning briefing")).toBeTruthy();
  expect(screen.getByText(/Disabled draft/)).toBeTruthy();
  expect(screen.getByText(/does not invent a conversation Run/)).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", { name: "Enable saved definition agent-on" }),
  );
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/agents/agent-one/enabled",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          expected_updated_at: "2026-10-11T10:00:00Z",
          enabled: true,
        }),
      }),
    ),
  );
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
  expect(
    screen
      .getByRole("link", { name: "Review agent agent-on" })
      .getAttribute("href"),
  ).toBe("/agents/agent-one");
});

it("pauses an enabled agent from the conversation without starting a Run", async () => {
  const enabled = { ...draft, enabled: true };
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      String(path).endsWith("/enabled")
        ? { ...enabled, enabled: false }
        : enabled,
  }));
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <AssistantAgentDraft agentId={enabled.id} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Pause agent agent-on" }),
  );
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/agents/agent-one/enabled",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          expected_updated_at: "2026-10-11T10:00:00Z",
          enabled: false,
        }),
      }),
    ),
  );
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});
