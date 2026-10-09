import { useState } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ExploreChoiceList } from "./ExploreChoiceList";

afterEach(cleanup);

function Host({ disabled = false }: { disabled?: boolean }) {
  const [checked, setChecked] = useState(true);
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        throw new Error("form submitted");
      }}
    >
      <ExploreChoiceList
        checked={checked}
        disabled={disabled}
        onChange={setChecked}
      >
        Let the agent find the relevant files
      </ExploreChoiceList>
      <button type="submit">Start coding</button>
    </form>
  );
}

it("moves through automatic file discovery without starting a Run", () => {
  render(<Host />);
  const option = screen.getByLabelText("Explore automatic");
  expect(option.tabIndex).toBe(0);
  expect(
    screen.getByText(/There is no inspectable exploration-policy Run/),
  ).toBeTruthy();
  expect(
    (
      screen.getByRole("checkbox", {
        name: /Let the agent find the relevant files/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
  fireEvent.keyDown(option.closest(".explore-choice-list") as HTMLElement, {
    key: "Enter",
  });
  expect(
    (
      screen.getByRole("checkbox", {
        name: /Let the agent find the relevant files/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(false);
  fireEvent.keyDown(option.closest(".explore-choice-list") as HTMLElement, {
    key: " ",
  });
  expect(
    (
      screen.getByRole("checkbox", {
        name: /Let the agent find the relevant files/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
});

it("does not change discovery while the toggle is disabled", () => {
  render(<Host disabled />);
  const option = screen.getByLabelText("Explore automatic");
  fireEvent.keyDown(option.closest(".explore-choice-list") as HTMLElement, {
    key: "Enter",
  });
  expect(
    (
      screen.getByRole("checkbox", {
        name: /Let the agent find the relevant files/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
});
