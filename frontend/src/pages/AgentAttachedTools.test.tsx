import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AgentAttachedTools } from "./AgentAttachedTools";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const catalog = [
  {
    name: "web_search",
    description: "Search public pages through the configured search service.",
    operational: true,
    required_permissions: ["network_read"],
  },
  {
    name: "http_fetch",
    description: "GET reviewed public pages.",
    operational: true,
    required_permissions: ["network_read"],
  },
  {
    name: "remember_report",
    description: "Save successful reports as observations.",
    operational: true,
    required_permissions: ["memory_write"],
  },
  {
    name: "browser",
    description: "Browser automation is not implemented for agents.",
    operational: false,
    required_permissions: [] as string[],
  },
];

function mount(
  names: string[],
  tools = catalog,
  onRemove?: (name: string) => void,
) {
  const fetch = vi.fn(async (path: string) => ({
    ok: !String(path).endsWith("/run") && !String(path).endsWith("/enabled"),
    json: async () => tools,
  }));
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <AgentAttachedTools
        names={names}
        agentId="agent-one"
        onRemove={onRemove}
      />
    </QueryClientProvider>,
  );
  return fetch;
}

it("reviews attached tools from the registry without inventing a Run", async () => {
  const fetch = mount(["web_search", "remember_report", "browser", "missing"]);
  expect(
    await screen.findByText(
      "Search public pages through the configured search service. network_read",
    ),
  ).toBeTruthy();
  expect(screen.getByText("web_search")).toBeTruthy();
  expect(screen.getByText("Remember reports")).toBeTruthy();
  expect(screen.getByLabelText("Tool browser")).toBeTruthy();
  expect(screen.getByText(/— Unavailable/)).toBeTruthy();
  expect(
    screen.getByText("Browser automation is not implemented for agents."),
  ).toBeTruthy();
  expect(screen.getByLabelText("Tool missing")).toBeTruthy();
  expect(screen.getByText("missing")).toBeTruthy();
  expect(screen.getByText("Not in the tool registry.")).toBeTruthy();
  expect(screen.queryByRole("button", { name: /Run now/ })).toBeNull();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
  expect(
    fetch.mock.calls.some((call) => String(call[0]).endsWith("/agents/tools")),
  ).toBe(true);
});

it("moves through attached tools with arrow keys without inventing a Run", async () => {
  const fetch = mount(["web_search", "http_fetch"]);
  expect(await screen.findByText("HTTP fetch")).toBeTruthy();
  const first = screen.getByLabelText("Tool web_search");
  const second = screen.getByLabelText("Tool http_fetch");
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  fireEvent.keyDown(first.closest(".agent-choice-list") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  fireEvent.keyDown(second.closest(".agent-choice-list") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
  fireEvent.keyDown(first.closest(".agent-choice-list") as HTMLElement, {
    key: "Enter",
  });
  fireEvent.keyDown(first.closest(".agent-choice-list") as HTMLElement, {
    key: " ",
  });
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});

it("offers Remove on unavailable tools without inventing a Run", async () => {
  const onRemove = vi.fn();
  const fetch = mount(["web_search", "browser", "missing"], catalog, onRemove);
  expect(
    await screen.findByText(
      "Browser automation is not implemented for agents.",
    ),
  ).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: "Remove tool web_search agent-on" }),
  ).toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "Remove tool browser agent-on" }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Remove tool missing agent-on" }),
  );
  expect(onRemove.mock.calls).toEqual([["browser"], ["missing"]]);
  expect(screen.queryByRole("button", { name: /Enable/ })).toBeNull();
  expect(
    fetch.mock.calls.every(
      (call) =>
        !String(call[0]).endsWith("/run") &&
        !String(call[0]).endsWith("/enabled"),
    ),
  ).toBe(true);
});
