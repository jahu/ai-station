import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { RunEvent } from "../api";
import RunTimeline from "./RunTimeline";

afterEach(cleanup);
const event = (
  sequence: number,
  type = "agent.delta",
  text = "word ",
): RunEvent => ({
  id: String(sequence),
  sequence,
  event_type: type,
  payload: { text },
  created_at: "2026-10-06T10:00:00Z",
});
it("keeps streaming tokens out of Activity and presents readable full output", () => {
  const events = [
    event(1, "run.started"),
    ...Array.from({ length: 2000 }, (_, i) => event(i + 2)),
    event(2002, "stderr", "diagnostic"),
    event(2003, "run.completed"),
  ];
  const { container } = render(<RunTimeline events={events} live={false} />);
  expect(container.querySelectorAll(".timeline article")).toHaveLength(2);
  expect(screen.getByText("run.completed")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Output" }));
  const output = screen.getByLabelText("Captured output").textContent;
  expect(output).toContain("word ".repeat(2000));
  expect(output).toContain("[stderr]\ndiagnostic");
  fireEvent.click(screen.getByRole("button", { name: "All events" }));
  expect(container.querySelectorAll(".timeline article")).toHaveLength(50);
});
it("moves through execution events with arrow keys", () => {
  render(
    <RunTimeline
      events={[
        event(1, "run.started", "start"),
        event(2, "tool.completed", "done"),
      ]}
      live={false}
    />,
  );
  const first = screen.getByLabelText("Event run.started 1");
  const second = screen.getByLabelText("Event tool.completed 2");
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(
    screen.getByRole("region", { name: "Execution timeline" }),
  ).toBeTruthy();
  expect(screen.getByText(/Arrow keys choose an event/)).toBeTruthy();
  fireEvent.keyDown(first.closest(".run-event-list") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  expect(document.activeElement).toBe(second);
  fireEvent.keyDown(second.closest(".run-event-list") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
});
it("preserves earlier pages while live events arrive and returns to the latest", () => {
  const events = Array.from({ length: 120 }, (_, i) =>
    event(i + 1, "tool.completed", String(i + 1)),
  );
  const { container, rerender } = render(<RunTimeline events={events} live />);
  fireEvent.click(screen.getByRole("button", { name: "Older events" }));
  expect(screen.getByText(/21–70 of 120 activity events/)).toBeTruthy();
  rerender(
    <RunTimeline
      events={[...events, event(121, "run.completed")]}
      live={false}
    />,
  );
  expect(screen.getByText(/21–70 of 121 activity events/)).toBeTruthy();
  expect(container.querySelectorAll(".timeline article")).toHaveLength(50);
  fireEvent.click(screen.getByRole("button", { name: "Older events" }));
  expect(container.querySelectorAll(".timeline article")).toHaveLength(20);
  expect(
    (screen.getByRole("button", { name: "Older events" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Latest events" }));
  expect(screen.getByText("run.completed")).toBeTruthy();
  expect(screen.getByText(/72–121 of 121 activity events/)).toBeTruthy();
});
