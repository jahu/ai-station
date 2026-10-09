import { useState } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import {
  AvatarClipChoiceList,
  AvatarQualityChoiceList,
} from "./AvatarChoiceLists";

afterEach(cleanup);

function QualityHost({ disabled = false }: { disabled?: boolean }) {
  const [value, setValue] = useState(384);
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        throw new Error("form submitted");
      }}
    >
      <AvatarQualityChoiceList
        value={value}
        disabled={disabled}
        onChange={setValue}
      />
      <button type="submit">Generate avatar video</button>
    </form>
  );
}

function ClipHost({ disabled = false }: { disabled?: boolean }) {
  const [value, setValue] = useState(81);
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        throw new Error("form submitted");
      }}
    >
      <AvatarClipChoiceList
        value={value}
        disabled={disabled}
        onChange={setValue}
      />
      <button type="submit">Generate avatar video</button>
    </form>
  );
}

it("moves through Quality without queueing a Run", () => {
  render(<QualityHost />);
  const balanced = screen.getByLabelText("Quality 384");
  expect(balanced.tabIndex).toBe(0);
  expect(screen.getByText(/There is no inspectable quality Run/)).toBeTruthy();
  expect(
    (
      screen.getByRole("radio", { name: /Balanced · 384 px/ }) as HTMLInputElement
    ).checked,
  ).toBe(true);
  const list = balanced.closest(".avatar-quality-choice-list") as HTMLElement;
  fireEvent.keyDown(list, { key: "Home" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    (screen.getByRole("radio", { name: /Draft · 256 px/ }) as HTMLInputElement)
      .checked,
  ).toBe(true);
  expect(screen.getByLabelText("Quality 256").tabIndex).toBe(0);
});

it("does not change Quality while the list is disabled", () => {
  render(<QualityHost disabled />);
  const list = screen
    .getByLabelText("Quality 384")
    .closest(".avatar-quality-choice-list") as HTMLElement;
  fireEvent.keyDown(list, { key: "Home" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    (
      screen.getByRole("radio", { name: /Balanced · 384 px/ }) as HTMLInputElement
    ).checked,
  ).toBe(true);
});

it("moves through Clip length without queueing a Run", () => {
  render(<ClipHost />);
  const longest = screen.getByLabelText("Clip 81");
  expect(longest.tabIndex).toBe(0);
  expect(
    screen.getByText(/There is no inspectable clip-length Run/),
  ).toBeTruthy();
  const list = longest.closest(".avatar-clip-choice-list") as HTMLElement;
  fireEvent.keyDown(list, { key: "Home" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    (
      screen.getByRole("radio", { name: /Up to 0.68 seconds/ }) as HTMLInputElement
    ).checked,
  ).toBe(true);
  expect(screen.getByLabelText("Clip 17").tabIndex).toBe(0);
});

it("does not submit the form when Enter selects a focused Quality", () => {
  render(<QualityHost />);
  fireEvent.keyDown(screen.getByRole("radio", { name: /Balanced · 384 px/ }), {
    key: "Enter",
  });
  expect(
    (
      screen.getByRole("radio", { name: /Balanced · 384 px/ }) as HTMLInputElement
    ).checked,
  ).toBe(true);
});
