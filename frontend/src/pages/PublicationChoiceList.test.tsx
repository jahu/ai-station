import { useState } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { PublicationChoiceList } from "./PublicationChoiceList";

afterEach(cleanup);

function Host({ disabled = false }: { disabled?: boolean }) {
  const [checked, setChecked] = useState(false);
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        throw new Error("form submitted");
      }}
    >
      <PublicationChoiceList
        checked={checked}
        disabled={disabled}
        onChange={setChecked}
      >
        I approve publishing this commit and PR text to the GitHub repository
        shown above.
      </PublicationChoiceList>
      <button type="submit">Publish branch and create draft PR</button>
    </form>
  );
}

it("moves through publication approval without publishing", () => {
  render(<Host />);
  const option = screen.getByLabelText("Publication approve");
  expect(option.tabIndex).toBe(0);
  expect(
    screen.getByText(/There is no inspectable publication-approval Run/),
  ).toBeTruthy();
  expect(
    (screen.getByRole("checkbox", { name: /I approve publishing/ }) as HTMLInputElement)
      .checked,
  ).toBe(false);
  fireEvent.keyDown(option.closest(".publication-choice-list") as HTMLElement, {
    key: "Enter",
  });
  expect(
    (screen.getByRole("checkbox", { name: /I approve publishing/ }) as HTMLInputElement)
      .checked,
  ).toBe(true);
  fireEvent.keyDown(option.closest(".publication-choice-list") as HTMLElement, {
    key: " ",
  });
  expect(
    (screen.getByRole("checkbox", { name: /I approve publishing/ }) as HTMLInputElement)
      .checked,
  ).toBe(false);
});

it("does not approve publication while the toggle is disabled", () => {
  render(<Host disabled />);
  const option = screen.getByLabelText("Publication approve");
  fireEvent.keyDown(option.closest(".publication-choice-list") as HTMLElement, {
    key: "Enter",
  });
  expect(
    (screen.getByRole("checkbox", { name: /I approve publishing/ }) as HTMLInputElement)
      .checked,
  ).toBe(false);
});
