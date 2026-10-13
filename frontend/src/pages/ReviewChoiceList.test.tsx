import { useState } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ReviewChoiceList } from "./ReviewChoiceList";

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
      <ReviewChoiceList
        checked={checked}
        disabled={disabled}
        onChange={setChecked}
      >
        I reviewed the diff and validation results.
      </ReviewChoiceList>
      <button type="submit">Commit reviewed changes</button>
    </form>
  );
}

it("moves through commit review without queueing a commit", () => {
  render(<Host />);
  const option = screen.getByLabelText("Review commit");
  expect(option.tabIndex).toBe(0);
  expect(
    screen.getByText(/There is no inspectable review-ack Run/),
  ).toBeTruthy();
  expect(
    (
      screen.getByRole("checkbox", {
        name: /I reviewed the diff/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(false);
  fireEvent.keyDown(option.closest(".review-choice-list") as HTMLElement, {
    key: "Enter",
  });
  expect(
    (
      screen.getByRole("checkbox", {
        name: /I reviewed the diff/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
  fireEvent.keyDown(option.closest(".review-choice-list") as HTMLElement, {
    key: " ",
  });
  expect(
    (
      screen.getByRole("checkbox", {
        name: /I reviewed the diff/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(false);
});

it("does not acknowledge review while the toggle is disabled", () => {
  render(<Host disabled />);
  const option = screen.getByLabelText("Review commit");
  fireEvent.keyDown(option.closest(".review-choice-list") as HTMLElement, {
    key: "Enter",
  });
  expect(
    (
      screen.getByRole("checkbox", {
        name: /I reviewed the diff/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(false);
});
