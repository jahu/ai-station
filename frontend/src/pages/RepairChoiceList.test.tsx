import { useState } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { RepairChoiceList } from "./RepairChoiceList";

afterEach(cleanup);

function Host({ disabled = false }: { disabled?: boolean }) {
  const [value, setValue] = useState(0);
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        throw new Error("form submitted");
      }}
    >
      <RepairChoiceList
        value={value}
        disabled={disabled}
        onChange={setValue}
      />
      <button type="submit">Start coding</button>
    </form>
  );
}

it("moves through the local repair budget without starting a Run", () => {
  render(<Host />);
  const off = screen.getByLabelText("Repair 0");
  expect(off.tabIndex).toBe(0);
  expect(
    screen.getByText(/There is no inspectable repair-budget Run/),
  ).toBeTruthy();
  expect(
    (screen.getByRole("radio", { name: /Off — ask me first/ }) as HTMLInputElement)
      .checked,
  ).toBe(true);
  const list = off.closest(".repair-choice-list") as HTMLElement;
  fireEvent.keyDown(list, { key: "ArrowDown" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    (screen.getByRole("radio", { name: /One attempt/ }) as HTMLInputElement)
      .checked,
  ).toBe(true);
  fireEvent.keyDown(list, { key: "End" });
  fireEvent.keyDown(list, { key: " " });
  expect(
    (
      screen.getByRole("radio", {
        name: /Up to two attempts/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
  expect(screen.getByLabelText("Repair 2").tabIndex).toBe(0);
});

it("does not change the budget while the list is disabled", () => {
  render(<Host disabled />);
  const list = screen.getByLabelText("Repair 0").closest(
    ".repair-choice-list",
  ) as HTMLElement;
  fireEvent.keyDown(list, { key: "ArrowDown" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    (screen.getByRole("radio", { name: /Off — ask me first/ }) as HTMLInputElement)
      .checked,
  ).toBe(true);
});

it("does not submit the form when Enter selects a focused budget", () => {
  render(<Host />);
  fireEvent.keyDown(screen.getByRole("radio", { name: /Off — ask me first/ }), {
    key: "Enter",
  });
  expect(
    (screen.getByRole("radio", { name: /Off — ask me first/ }) as HTMLInputElement)
      .checked,
  ).toBe(true);
});
