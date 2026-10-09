import { useState } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ProjectChoiceList } from "./ProjectChoiceList";

afterEach(cleanup);

const PROJECTS = [
  { id: "alpha", name: "Alpha", preferred_executor: "cursor" },
  { id: "beta", name: "Beta", preferred_executor: "codex" },
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
      <ProjectChoiceList
        projects={PROJECTS}
        value={value}
        disabled={disabled}
        onChange={setValue}
      />
      <button type="submit">Start coding</button>
    </form>
  );
}

it("moves through coding projects without starting a Run", () => {
  render(<Host />);
  const first = screen.getByLabelText("Project alpha");
  expect(first.tabIndex).toBe(0);
  expect(
    screen.getByText(/There is no inspectable project-selection Run/),
  ).toBeTruthy();
  expect(screen.getByText("Preferred executor: Cursor")).toBeTruthy();
  expect(
    (screen.getByRole("radio", { name: /^Alpha/ }) as HTMLInputElement)
      .checked,
  ).toBe(false);
  const list = first.closest(".project-choice-list") as HTMLElement;
  fireEvent.keyDown(list, { key: "End" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    (screen.getByRole("radio", { name: /^Beta/ }) as HTMLInputElement).checked,
  ).toBe(true);
  expect(screen.getByLabelText("Project beta").tabIndex).toBe(0);
});

it("does not change the project while the list is disabled", () => {
  render(<Host disabled />);
  const list = screen
    .getByLabelText("Project alpha")
    .closest(".project-choice-list") as HTMLElement;
  fireEvent.keyDown(list, { key: "End" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    (screen.getByRole("radio", { name: /^Alpha/ }) as HTMLInputElement)
      .checked,
  ).toBe(false);
  expect(
    (screen.getByRole("radio", { name: /^Beta/ }) as HTMLInputElement).checked,
  ).toBe(false);
});

it("does not submit the form when Enter selects a focused project", () => {
  render(<Host />);
  fireEvent.keyDown(screen.getByRole("radio", { name: /^Alpha/ }), {
    key: "Enter",
  });
  expect(
    (screen.getByRole("radio", { name: /^Alpha/ }) as HTMLInputElement)
      .checked,
  ).toBe(true);
});
