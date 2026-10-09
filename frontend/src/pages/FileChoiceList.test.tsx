import { useState } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { FileChoiceList } from "./FileChoiceList";

afterEach(cleanup);

function Host() {
  const [files, setFiles] = useState("README.md\nsrc/app.py");
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        throw new Error("form submitted");
      }}
    >
      <FileChoiceList
        files={files}
        onChange={setFiles}
        label="Selected files"
      />
    </form>
  );
}

it("moves through coding file checkboxes without starting a Run", () => {
  render(<Host />);
  const first = screen.getByLabelText("Edit file README.md");
  const second = screen.getByLabelText("Edit file src/app.py");
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(
    screen.getByText(/There is no inspectable file-selection Run/),
  ).toBeTruthy();
  fireEvent.keyDown(first.closest(".file-choice-list") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(document.activeElement).toBe(second);
  fireEvent.keyDown(second.closest(".file-choice-list") as HTMLElement, {
    key: "Enter",
  });
  expect(screen.queryByLabelText("Edit file src/app.py")).toBeNull();
  expect(screen.getByLabelText("Edit file README.md").tabIndex).toBe(0);
  expect(
    (screen.getByLabelText("Selected files") as HTMLTextAreaElement).value,
  ).toBe("README.md");
});
