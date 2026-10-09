import { useState } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import {
  ImageOperationChoiceList,
  type ImageOperation,
} from "./ImageOperationChoiceList";

afterEach(cleanup);

function Host({ disabled = false }: { disabled?: boolean }) {
  const [value, setValue] = useState<ImageOperation>("t2i");
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        throw new Error("form submitted");
      }}
    >
      <ImageOperationChoiceList
        value={value}
        disabled={disabled}
        onChange={setValue}
      />
      <button type="submit">Queue generate</button>
    </form>
  );
}

it("moves through image operations without queueing a Run", () => {
  render(<Host />);
  const generate = screen.getByLabelText("Operation t2i");
  expect(generate.tabIndex).toBe(0);
  expect(screen.getByText(/There is no inspectable operation Run/)).toBeTruthy();
  expect(generate.getAttribute("aria-pressed")).toBe("true");
  const list = generate.closest(".image-operation-choice-list") as HTMLElement;
  fireEvent.keyDown(list, { key: "End" });
  fireEvent.keyDown(list, { key: "Enter" });
  const upscale = screen.getByLabelText("Operation upscale");
  expect(upscale.getAttribute("aria-pressed")).toBe("true");
  expect(upscale.tabIndex).toBe(0);
});

it("does not change the operation while the list is disabled", () => {
  render(<Host disabled />);
  const list = screen
    .getByLabelText("Operation t2i")
    .closest(".image-operation-choice-list") as HTMLElement;
  fireEvent.keyDown(list, { key: "End" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    screen.getByLabelText("Operation t2i").getAttribute("aria-pressed"),
  ).toBe("true");
});

it("does not submit the form when Enter selects a focused operation", () => {
  render(<Host />);
  fireEvent.keyDown(screen.getByLabelText("Operation t2i"), {
    key: "Enter",
  });
  expect(
    screen.getByLabelText("Operation t2i").getAttribute("aria-pressed"),
  ).toBe("true");
});
