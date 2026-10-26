import { useState } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { CodingModelChoiceList } from "./CodingModelChoiceList";

afterEach(cleanup);

const MODELS = [
  { id: "available-model", name: "Available model" },
  { id: "other-model", name: "Other model" },
];

function Host({
  disabled = false,
  models = MODELS,
}: {
  disabled?: boolean;
  models?: { id: string; name: string }[];
}) {
  const [value, setValue] = useState("");
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        throw new Error("form submitted");
      }}
    >
      <CodingModelChoiceList
        models={models}
        value={value}
        disabled={disabled}
        onChange={setValue}
      />
      <button type="submit">Start coding</button>
    </form>
  );
}

it("moves through native Cursor and Codex models without starting a Run", () => {
  render(<Host />);
  const auto = screen.getByLabelText("Model auto");
  expect(auto.tabIndex).toBe(0);
  expect(screen.getByText(/Model choices. Use arrow keys/)).toBeTruthy();
  expect(
    (screen.getByRole("radio", { name: /^Auto/ }) as HTMLInputElement).checked,
  ).toBe(true);
  const list = auto.closest(".coding-model-choice-list") as HTMLElement;
  fireEvent.keyDown(list, { key: "End" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    (screen.getByRole("radio", { name: /Other model/ }) as HTMLInputElement)
      .checked,
  ).toBe(true);
  expect(screen.getByLabelText("Model other-model").tabIndex).toBe(0);
});

it("keeps Auto when the installed catalog is empty", () => {
  render(<Host models={[]} />);
  expect(screen.getByLabelText("Model auto")).toBeTruthy();
  expect(screen.queryByLabelText("Model available-model")).toBeNull();
  expect(
    (screen.getByRole("radio", { name: /^Auto/ }) as HTMLInputElement).checked,
  ).toBe(true);
});

it("does not change the model while the list is disabled", () => {
  render(<Host disabled />);
  const list = screen
    .getByLabelText("Model auto")
    .closest(".coding-model-choice-list") as HTMLElement;
  fireEvent.keyDown(list, { key: "End" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    (screen.getByRole("radio", { name: /^Auto/ }) as HTMLInputElement).checked,
  ).toBe(true);
});

it("does not submit the form when Enter selects a focused model", () => {
  render(<Host />);
  fireEvent.keyDown(screen.getByRole("radio", { name: /^Auto/ }), {
    key: "Enter",
  });
  expect(
    (screen.getByRole("radio", { name: /^Auto/ }) as HTMLInputElement).checked,
  ).toBe(true);
});
