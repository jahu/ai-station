import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ActionChoiceList } from "./ActionChoiceList";

afterEach(cleanup);

function Host({ disabled = false, submit = vi.fn() }) {
  const [value, setValue] = useState("auto");
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <ActionChoiceList value={value} disabled={disabled} onChange={setValue} />
      <button type="submit">Send</button>
    </form>
  );
}

it("offers every action in a compact control and explains the selected action", () => {
  render(<Host />);
  const action = screen.getByRole("combobox", {
    name: "Action",
  }) as HTMLSelectElement;
  expect(action.value).toBe("auto");
  expect(screen.getAllByRole("option")).toHaveLength(22);
  expect(screen.queryByRole("radio")).toBeNull();
  fireEvent.change(action, { target: { value: "image.edit" } });
  expect(action.value).toBe("image.edit");
  expect(
    screen.getByText("Modify one image while preserving the original."),
  ).toBeTruthy();
});

it("disables action selection during execution", () => {
  render(<Host disabled />);
  expect(
    (screen.getByRole("combobox", { name: "Action" }) as HTMLSelectElement)
      .disabled,
  ).toBe(true);
});

it("does not send a task when Enter is pressed in the action picker", () => {
  const submit = vi.fn();
  render(<Host submit={submit} />);
  const action = screen.getByRole("combobox", { name: "Action" });
  expect(fireEvent.keyDown(action, { key: "Enter", cancelable: true })).toBe(
    false,
  );
  expect(submit).not.toHaveBeenCalled();
});

it("explains local automatic vision loading when images are inspected", () => {
  render(<Host />);
  fireEvent.change(screen.getByRole("combobox", { name: "Action" }), {
    target: { value: "image.describe" },
  });
  expect(screen.getByText(/reads their contents locally/)).toBeTruthy();
});
