import { useState } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { RuntimeChoiceList } from "./RuntimeChoiceList";

afterEach(cleanup);

const INSTANCES = [
  { id: "run-a", name: "27B", status: "ready" },
  { id: "run-b", name: "8B", status: "loading" },
];

function Host({ disabled = false }: { disabled?: boolean }) {
  const [value, setValue] = useState("");
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        throw new Error("form submitted");
      }}
    >
      <RuntimeChoiceList
        instances={INSTANCES}
        value={value}
        disabled={disabled}
        onChange={setValue}
      />
      <button type="submit">Send</button>
    </form>
  );
}

it("moves through owned runtimes without sending", () => {
  render(<Host />);
  const first = screen.getByLabelText("Runtime run-a");
  expect(first.tabIndex).toBe(0);
  expect(
    screen.getByText(/AI Station runtime choices. Use arrow keys/),
  ).toBeTruthy();
  expect(
    screen.getByText(/Only AI Station–managed llama.cpp instances are listed/),
  ).toBeTruthy();
  const list = first.closest(".runtime-choice-list") as HTMLElement;
  fireEvent.keyDown(list, { key: "End" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    (screen.getByRole("radio", { name: /^8B/ }) as HTMLInputElement).checked,
  ).toBe(true);
  expect(screen.getByLabelText("Runtime run-b").tabIndex).toBe(0);
});

it("does not change the runtime while the list is disabled", () => {
  render(<Host disabled />);
  const list = screen
    .getByLabelText("Runtime run-a")
    .closest(".runtime-choice-list") as HTMLElement;
  fireEvent.keyDown(list, { key: "End" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    (screen.getByRole("radio", { name: /^27B/ }) as HTMLInputElement).checked,
  ).toBe(false);
});

it("does not submit the form when Enter selects a focused runtime", () => {
  render(<Host />);
  fireEvent.keyDown(screen.getByRole("radio", { name: /^27B/ }), {
    key: "Enter",
  });
  expect(
    (screen.getByRole("radio", { name: /^27B/ }) as HTMLInputElement).checked,
  ).toBe(true);
});
