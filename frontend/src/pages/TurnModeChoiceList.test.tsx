import { useState } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { TurnModeChoiceList, type TurnMode } from "./TurnModeChoiceList";

afterEach(cleanup);

function Host({
  disabled = false,
  orchestrator = false,
}: {
  disabled?: boolean;
  orchestrator?: boolean;
}) {
  const [value, setValue] = useState<TurnMode>("auto");
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        throw new Error("form submitted");
      }}
    >
      <TurnModeChoiceList
        value={value}
        orchestrator={orchestrator}
        disabled={disabled}
        onChange={setValue}
      />
      <button type="submit">Send</button>
    </form>
  );
}

it("moves through this-turn mode without sending", () => {
  render(<Host />);
  const auto = screen.getByLabelText("Turn auto");
  expect(auto.tabIndex).toBe(0);
  expect(
    screen.getByText(/There is no inspectable turn-mode Run/),
  ).toBeTruthy();
  expect(
    (
      screen.getByRole("radio", {
        name: /Conversation default \(Conversation only\)/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
  const list = auto.closest(".turn-choice-list") as HTMLElement;
  fireEvent.keyDown(list, { key: "End" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    (
      screen.getByRole("radio", {
        name: /Platform assistant/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
  expect(screen.getByLabelText("Turn orchestrator").tabIndex).toBe(0);
});

it("does not change the mode while the list is disabled", () => {
  render(<Host disabled />);
  const list = screen
    .getByLabelText("Turn auto")
    .closest(".turn-choice-list") as HTMLElement;
  fireEvent.keyDown(list, { key: "End" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    (
      screen.getByRole("radio", {
        name: /Conversation default \(Conversation only\)/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
});

it("does not submit the form when Enter selects a focused mode", () => {
  render(<Host />);
  fireEvent.keyDown(
    screen.getByRole("radio", {
      name: /Conversation default \(Conversation only\)/,
    }),
    { key: "Enter" },
  );
  expect(
    (
      screen.getByRole("radio", {
        name: /Conversation default \(Conversation only\)/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
});
