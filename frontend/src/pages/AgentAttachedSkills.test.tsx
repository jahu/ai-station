import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AgentAttachedSkills } from "./AgentAttachedSkills";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const skills = [
  {
    id: "station-briefing",
    name: "Station briefing",
    version: "1.0.0",
    description: "Local status report format",
    required_permissions: [] as string[],
    instructions: "Always mention GPU memory when it appears.",
  },
  {
    id: "daily-brief",
    name: "Daily brief",
    version: "1.2.0",
    description: "Morning format",
    required_permissions: ["network_read"],
    instructions: "Cite only supplied tool results.",
  },
];

function mount(
  ids: string[],
  catalog = skills,
  onRemove?: (id: string) => void,
) {
  const fetch = vi.fn(async (path: string) => ({
    ok: !String(path).endsWith("/run") && !String(path).endsWith("/enabled"),
    json: async () => catalog,
  }));
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <AgentAttachedSkills ids={ids} agentId="agent-one" onRemove={onRemove} />
    </QueryClientProvider>,
  );
  return fetch;
}

it("reviews attached skill instructions without inventing a Run", async () => {
  const fetch = mount(["station-briefing", "missing-skill"]);
  expect(await screen.findByText("Station briefing")).toBeTruthy();
  expect(
    screen.getByText("station-briefing 1.0.0. Local status report format"),
  ).toBeTruthy();
  fireEvent.click(
    screen.getByText("Review Station briefing station-briefing instructions"),
  );
  expect(
    screen.getByText("Always mention GPU memory when it appears."),
  ).toBeTruthy();
  expect(
    screen.getByLabelText("Skill missing-skill missing-skill"),
  ).toBeTruthy();
  expect(screen.getByText("missing-skill")).toBeTruthy();
  expect(screen.getByText("Not in the installed catalog.")).toBeTruthy();
  expect(screen.queryByRole("button", { name: /Run now/ })).toBeNull();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});

it("moves through attached skills with arrow keys without inventing a Run", async () => {
  const fetch = mount(["station-briefing", "daily-brief"]);
  const first = await screen.findByLabelText(
    "Skill Station briefing station-briefing",
  );
  const second = screen.getByLabelText("Skill Daily brief daily-brief");
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
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).endsWith("/run")),
  ).toBe(true);
});

it("offers Remove on a missing skill without inventing a Run", async () => {
  const onRemove = vi.fn();
  const fetch = mount(["station-briefing", "missing-skill"], skills, onRemove);
  expect(await screen.findByText("Not in the installed catalog.")).toBeTruthy();
  expect(
    screen.queryByRole("button", {
      name: "Remove skill station-briefing agent-on",
    }),
  ).toBeNull();
  fireEvent.click(
    screen.getByRole("button", {
      name: "Remove skill missing-skill agent-on",
    }),
  );
  expect(onRemove.mock.calls).toEqual([["missing-skill"]]);
  expect(screen.queryByRole("button", { name: /Enable/ })).toBeNull();
  expect(
    fetch.mock.calls.every(
      (call) =>
        !String(call[0]).endsWith("/run") &&
        !String(call[0]).endsWith("/enabled"),
    ),
  ).toBe(true);
});
