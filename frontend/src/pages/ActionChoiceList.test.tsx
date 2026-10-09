import { useState } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ActionChoiceList } from "./ActionChoiceList";

afterEach(cleanup);

function Host({ disabled = false }: { disabled?: boolean }) {
  const [value, setValue] = useState("auto");
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        throw new Error("form submitted");
      }}
    >
      <ActionChoiceList value={value} disabled={disabled} onChange={setValue} />
      <button type="submit">Send</button>
    </form>
  );
}

it("moves through assistant actions without sending", () => {
  render(<Host />);
  const auto = screen.getByLabelText("Action auto");
  expect(auto.tabIndex).toBe(0);
  expect(
    screen.getByText(/There is no inspectable action-selection Run/),
  ).toBeTruthy();
  expect(
    (
      screen.getByRole("radio", {
        name: /Auto — let AI Station route this task/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
  const list = auto.closest(".assistant-action-choice-list") as HTMLElement;
  fireEvent.keyDown(list, { key: "End" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    (
      screen.getByRole("radio", {
        name: /Unload owned llama.cpp/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
  expect(screen.getByLabelText("Action runtime.stop").tabIndex).toBe(0);
});

it("does not change the action while the list is disabled", () => {
  render(<Host disabled />);
  const list = screen
    .getByLabelText("Action auto")
    .closest(".assistant-action-choice-list") as HTMLElement;
  fireEvent.keyDown(list, { key: "End" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    (
      screen.getByRole("radio", {
        name: /Auto — let AI Station route this task/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
});

it("does not submit the form when Enter selects a focused action", () => {
  render(<Host />);
  fireEvent.keyDown(
    screen.getByRole("radio", {
      name: /Auto — let AI Station route this task/,
    }),
    { key: "Enter" },
  );
  expect(
    (
      screen.getByRole("radio", {
        name: /Auto — let AI Station route this task/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
});
