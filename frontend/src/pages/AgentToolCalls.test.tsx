import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { RegistryToolCalls } from "./AgentToolCalls";

afterEach(() => cleanup());

it("lists recorded registry calls and their arguments without inventing a Run", () => {
  render(
    <RegistryToolCalls
      calls={[
        {
          id: "call-0-0",
          tool: "system_snapshot",
          arguments: {},
          round: 0,
        },
      ]}
    />,
  );
  expect(
    screen.getByRole("heading", { name: "Registry tool calls" }),
  ).toBeTruthy();
  expect(screen.getByText("system_snapshot")).toBeTruthy();
  expect(screen.getByText(/round 1/)).toBeTruthy();
  expect(screen.getByText("{}")).toBeTruthy();
  expect(screen.queryByRole("link")).toBeNull();
});

it("moves through registry tool calls with arrow keys", () => {
  render(
    <RegistryToolCalls
      calls={[
        {
          id: "call-0-0",
          tool: "system_snapshot",
          arguments: {},
          round: 0,
        },
        {
          id: "call-1-0",
          tool: "memory_search",
          arguments: { query: "last report" },
          round: 1,
        },
      ]}
    />,
  );
  const first = screen.getByLabelText("Call system_snapshot call-0-0");
  const second = screen.getByLabelText("Call memory_search call-1-0");
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(
    screen.getByRole("region", { name: "Registry tool calls" }),
  ).toBeTruthy();
  expect(screen.getByText(/Arrow keys choose a registry call/)).toBeTruthy();
  expect(
    screen.getByText(/There is no inspectable tool-call Run/),
  ).toBeTruthy();
  expect(screen.getByText(/"query": "last report"/)).toBeTruthy();
  fireEvent.keyDown(first.closest(".diagnostic-list") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  expect(document.activeElement).toBe(second);
  fireEvent.keyDown(second.closest(".diagnostic-list") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
});
