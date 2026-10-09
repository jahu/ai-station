import { useState } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ConsentChoiceList } from "./ConsentChoiceList";

afterEach(cleanup);

function Host({ disabled = false }: { disabled?: boolean }) {
  const [checked, setChecked] = useState(false);
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        throw new Error("form submitted");
      }}
    >
      <ConsentChoiceList
        checked={checked}
        disabled={disabled}
        onChange={setChecked}
      >
        Allow Cursor to receive this conversation.
      </ConsentChoiceList>
      <button type="submit">Start coding</button>
    </form>
  );
}

it("moves through coding consent without starting a Run", () => {
  render(<Host />);
  const option = screen.getByLabelText("Consent external_ai");
  expect(option.tabIndex).toBe(0);
  expect(screen.getByText(/There is no inspectable consent Run/)).toBeTruthy();
  expect(
    (
      screen.getByRole("checkbox", {
        name: /Allow Cursor to receive/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(false);
  fireEvent.keyDown(option.closest(".consent-choice-list") as HTMLElement, {
    key: "Enter",
  });
  expect(
    (
      screen.getByRole("checkbox", {
        name: /Allow Cursor to receive/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
  fireEvent.keyDown(option.closest(".consent-choice-list") as HTMLElement, {
    key: " ",
  });
  expect(
    (
      screen.getByRole("checkbox", {
        name: /Allow Cursor to receive/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(false);
});

it("does not grant consent while the toggle is disabled", () => {
  render(<Host disabled />);
  const option = screen.getByLabelText("Consent external_ai");
  fireEvent.keyDown(option.closest(".consent-choice-list") as HTMLElement, {
    key: "Enter",
  });
  expect(
    (
      screen.getByRole("checkbox", {
        name: /Allow Cursor to receive/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(false);
});
