import { useState } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { GpuTargetChoiceList } from "./GpuTargetChoiceList";

afterEach(cleanup);

function Host({ disabled = false }: { disabled?: boolean }) {
  const [value, setValue] = useState("auto");
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        throw new Error("form submitted");
      }}
    >
      <GpuTargetChoiceList
        value={value}
        disabled={disabled}
        gpus={[{ index: 7, name: "Test GPU" }]}
        onChange={setValue}
      />
      <button type="submit">Queue generate</button>
    </form>
  );
}

it("moves through media GPU targets without queueing a Run", () => {
  render(<Host />);
  const auto = screen.getByLabelText("Target GPU auto");
  expect(auto.tabIndex).toBe(0);
  expect(screen.getByText(/There is no inspectable GPU-target Run/)).toBeTruthy();
  expect(
    (
      screen.getByRole("radio", {
        name: /Auto · next available GPU/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
  const list = auto.closest(".gpu-target-choice-list") as HTMLElement;
  fireEvent.keyDown(list, { key: "End" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    (
      screen.getByRole("radio", { name: /GPU 7 · Test GPU/ }) as HTMLInputElement
    ).checked,
  ).toBe(true);
  expect(screen.getByLabelText("Target GPU 7").tabIndex).toBe(0);
});

it("does not change the target while the list is disabled", () => {
  render(<Host disabled />);
  const list = screen.getByLabelText("Target GPU auto").closest(
    ".gpu-target-choice-list",
  ) as HTMLElement;
  fireEvent.keyDown(list, { key: "End" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    (
      screen.getByRole("radio", {
        name: /Auto · next available GPU/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
});
