import { useState } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { GgufChoiceList } from "./GgufChoiceList";

afterEach(cleanup);

const MODELS = [
  { id: "gguf-1", name: "models · first.gguf" },
  { id: "gguf-2", name: "models · second.gguf" },
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
      <GgufChoiceList
        models={MODELS}
        value={value}
        disabled={disabled}
        onChange={setValue}
      />
      <button type="submit">Send</button>
    </form>
  );
}

it("moves through discovered GGUFs without sending", () => {
  render(<Host />);
  const first = screen.getByLabelText("GGUF gguf-1");
  expect(first.tabIndex).toBe(0);
  expect(
    screen.getByText(/There is no inspectable GGUF-selection Run/),
  ).toBeTruthy();
  expect(screen.queryByLabelText(/GGUF ollama/i)).toBeNull();
  const list = first.closest(".gguf-choice-list") as HTMLElement;
  fireEvent.keyDown(list, { key: "End" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    (screen.getByRole("radio", { name: /second.gguf/ }) as HTMLInputElement)
      .checked,
  ).toBe(true);
  expect(screen.getByLabelText("GGUF gguf-2").tabIndex).toBe(0);
});

it("does not change the GGUF while the list is disabled", () => {
  render(<Host disabled />);
  const list = screen
    .getByLabelText("GGUF gguf-1")
    .closest(".gguf-choice-list") as HTMLElement;
  fireEvent.keyDown(list, { key: "End" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    (screen.getByRole("radio", { name: /first.gguf/ }) as HTMLInputElement)
      .checked,
  ).toBe(false);
});

it("does not submit the form when Enter selects a focused GGUF", () => {
  render(<Host />);
  fireEvent.keyDown(screen.getByRole("radio", { name: /first.gguf/ }), {
    key: "Enter",
  });
  expect(
    (screen.getByRole("radio", { name: /first.gguf/ }) as HTMLInputElement)
      .checked,
  ).toBe(true);
});
