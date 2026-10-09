import { useState } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import {
  ImageBackendChoiceList,
  type ImageBackend,
} from "./ImageBackendChoiceList";

afterEach(cleanup);

function Host({ disabled = false }: { disabled?: boolean }) {
  const [value, setValue] = useState<ImageBackend>("qwen");
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        throw new Error("form submitted");
      }}
    >
      <ImageBackendChoiceList
        value={value}
        disabled={disabled}
        onChange={setValue}
      />
      <button type="submit">Queue generate</button>
    </form>
  );
}

it("moves through Generate backends without queueing a Run", () => {
  render(<Host />);
  const qwen = screen.getByLabelText("Backend qwen");
  expect(qwen.tabIndex).toBe(0);
  expect(screen.getByText(/There is no inspectable backend Run/)).toBeTruthy();
  expect(
    (screen.getByRole("radio", { name: /Qwen/ }) as HTMLInputElement).checked,
  ).toBe(true);
  const list = qwen.closest(".image-backend-choice-list") as HTMLElement;
  fireEvent.keyDown(list, { key: "End" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    (screen.getByRole("radio", { name: /Juggernaut/ }) as HTMLInputElement)
      .checked,
  ).toBe(true);
  expect(screen.getByLabelText("Backend juggernaut").tabIndex).toBe(0);
});

it("does not change the backend while the list is disabled", () => {
  render(<Host disabled />);
  const list = screen
    .getByLabelText("Backend qwen")
    .closest(".image-backend-choice-list") as HTMLElement;
  fireEvent.keyDown(list, { key: "End" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    (screen.getByRole("radio", { name: /Qwen/ }) as HTMLInputElement).checked,
  ).toBe(true);
});

it("does not submit the form when Enter selects a focused backend", () => {
  render(<Host />);
  fireEvent.keyDown(screen.getByRole("radio", { name: /Qwen/ }), {
    key: "Enter",
  });
  expect(
    (screen.getByRole("radio", { name: /Qwen/ }) as HTMLInputElement).checked,
  ).toBe(true);
});
