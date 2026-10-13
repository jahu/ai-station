import { useState } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { GpuChoiceList } from "./GpuChoiceList";

afterEach(cleanup);

function Host() {
  const [selected, setSelected] = useState<number[]>([0]);
  return (
    <GpuChoiceList
      gpus={[
        { index: 0, name: "GPU A", uuid: "gpu-zero-aaaa" },
        { index: 1, name: "GPU B", uuid: "gpu-one-bbbbbb" },
      ]}
      selected={selected}
      onChange={setSelected}
    />
  );
}

it("moves through GPU allocation checkboxes without inventing a Run", () => {
  render(<Host />);
  const first = screen.getByLabelText("Allocate GPU 0 gpu-zero");
  const second = screen.getByLabelText("Allocate GPU 1 gpu-one-");
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(
    screen.getByText(/There is no inspectable allocation Run/),
  ).toBeTruthy();
  fireEvent.keyDown(first.closest(".gpu-choice-list") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(document.activeElement).toBe(second);
  expect(
    (
      screen.getByRole("checkbox", {
        name: /GPU 1 · GPU B/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(false);
  fireEvent.keyDown(second.closest(".gpu-choice-list") as HTMLElement, {
    key: "Enter",
  });
  expect(
    (
      screen.getByRole("checkbox", {
        name: /GPU 1 · GPU B/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
  fireEvent.keyDown(second.closest(".gpu-choice-list") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
});
