import { useState } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ProjectChoiceList } from "./ProjectChoiceList";

afterEach(cleanup);

const PROJECTS = [
  { id: "alpha", name: "Alpha", preferred_executor: "cursor" },
  { id: "beta", name: "Beta", preferred_executor: "codex" },
];

function Host({ disabled = false }: { disabled?: boolean }) {
  const [value, setValue] = useState("");
  return (
    <MemoryRouter>
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
    </MemoryRouter>
  );
}

it("moves through coding projects without starting a Run", () => {
  render(<Host />);
  const first = screen.getByLabelText("Project alpha");
  expect(first.tabIndex).toBe(0);
  expect(screen.getByText(/Project choices. Use arrow keys/)).toBeTruthy();
  expect(screen.getByText("Preferred executor: Cursor")).toBeTruthy();
  expect(
    (screen.getByRole("radio", { name: /^Alpha/ }) as HTMLInputElement).checked,
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
    (screen.getByRole("radio", { name: /^Alpha/ }) as HTMLInputElement).checked,
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
    (screen.getByRole("radio", { name: /^Alpha/ }) as HTMLInputElement).checked,
  ).toBe(true);
});

it("opens tagged Runs from a coding project choice without starting a Run", () => {
  render(<Host />);
  expect(
    screen
      .getByRole("link", { name: "Inspect project alpha" })
      .getAttribute("href"),
  ).toBe("/projects/alpha");
  expect(
    screen
      .getByRole("link", { name: "View tagged Runs alpha" })
      .getAttribute("href"),
  ).toBe("/runs?project_id=alpha");
  expect(
    screen
      .getByRole("link", { name: "Inspect project beta" })
      .getAttribute("href"),
  ).toBe("/projects/beta");
  expect(
    screen
      .getByRole("link", { name: "View tagged Runs beta" })
      .getAttribute("href"),
  ).toBe("/runs?project_id=beta");
  fireEvent.click(screen.getByRole("link", { name: "View tagged Runs alpha" }));
  expect(
    (screen.getByRole("radio", { name: /^Alpha/ }) as HTMLInputElement).checked,
  ).toBe(false);
  expect(screen.queryByRole("button", { name: /Enable/i })).toBeNull();
  expect(screen.queryByRole("button", { name: /Run now/i })).toBeNull();
});
