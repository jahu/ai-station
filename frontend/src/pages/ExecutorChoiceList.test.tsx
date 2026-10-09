import { useState } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import {
  ExecutorChoiceList,
  type CodingExecutorChoice,
} from "./ExecutorChoiceList";

afterEach(cleanup);

function Host({ disabled = false }: { disabled?: boolean }) {
  const [value, setValue] = useState<CodingExecutorChoice>("auto");
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        throw new Error("form submitted");
      }}
    >
      <ExecutorChoiceList
        value={value}
        disabled={disabled}
        onChange={setValue}
      />
      <button type="submit">Start coding</button>
    </form>
  );
}

it("moves through coding executors without starting a Run", () => {
  render(<Host />);
  const auto = screen.getByLabelText("Executor auto");
  expect(auto.tabIndex).toBe(0);
  expect(screen.getByText(/There is no inspectable executor Run/)).toBeTruthy();
  expect(screen.queryByLabelText("Executor claude")).toBeNull();
  expect(
    (screen.getByRole("radio", { name: /^Auto/ }) as HTMLInputElement).checked,
  ).toBe(true);
  const list = auto.closest(".executor-choice-list") as HTMLElement;
  fireEvent.keyDown(list, { key: "End" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    (screen.getByRole("radio", { name: /^Codex/ }) as HTMLInputElement).checked,
  ).toBe(true);
  expect(screen.getByLabelText("Executor codex").tabIndex).toBe(0);
});

it("does not change the executor while the list is disabled", () => {
  render(<Host disabled />);
  const list = screen
    .getByLabelText("Executor auto")
    .closest(".executor-choice-list") as HTMLElement;
  fireEvent.keyDown(list, { key: "End" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    (screen.getByRole("radio", { name: /^Auto/ }) as HTMLInputElement).checked,
  ).toBe(true);
});

it("does not submit the form when Enter selects a focused executor", () => {
  render(<Host />);
  fireEvent.keyDown(screen.getByRole("radio", { name: /^Auto/ }), {
    key: "Enter",
  });
  expect(
    (screen.getByRole("radio", { name: /^Auto/ }) as HTMLInputElement).checked,
  ).toBe(true);
});
