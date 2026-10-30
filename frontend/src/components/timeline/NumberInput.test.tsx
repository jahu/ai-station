import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import NumberInput from "./NumberInput";
afterEach(cleanup);
it("retains decimal typing while keeping exact frames and restores empty input on blur", () => {
  function Fixture() {
    const [frames, setFrames] = useState(0);
    return (
      <>
        <NumberInput
          aria-label="Seconds"
          value={Number((frames / 24).toFixed(3))}
          onChange={(e) => setFrames(Math.round(Number(e.target.value) * 24))}
        />
        <output>{frames}</output>
      </>
    );
  }
  render(<Fixture />);
  const input = screen.getByLabelText("Seconds") as HTMLInputElement;
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value: "0.2" } });
  expect(input.value).toBe("0.2");
  fireEvent.change(input, { target: { value: "0.25" } });
  expect(screen.getByRole("status").textContent).toBe("6");
  fireEvent.blur(input);
  expect(input.value).toBe("0.25");
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value: "" } });
  fireEvent.blur(input);
  expect(input.value).toBe("0.25");
});
