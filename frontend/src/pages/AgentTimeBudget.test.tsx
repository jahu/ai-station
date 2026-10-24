import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import AgentTimeBudget from "./AgentTimeBudget";

afterEach(cleanup);

function Editor({ initial = "600", changed = vi.fn() }) {
  const [value, setValue] = useState(initial);
  return (
    <AgentTimeBudget
      value={value}
      onChange={(next) => {
        changed(next);
        setValue(next);
      }}
    />
  );
}

it("offers readable multi-hour presets without editing a saved budget on mount", () => {
  const changed = vi.fn();
  render(<Editor changed={changed} />);
  expect((screen.getByLabelText("Time limit") as HTMLSelectElement).value).toBe(
    "600",
  );
  expect(changed).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Time limit"), {
    target: { value: "7200" },
  });
  expect(changed).toHaveBeenLastCalledWith("7200");
  fireEvent.change(screen.getByLabelText("Time limit"), {
    target: { value: "14400" },
  });
  expect(changed).toHaveBeenLastCalledWith("14400");
  expect(screen.getByText(/Covers waiting for resources/)).toBeTruthy();
});

it("preserves exact nonstandard durations and exposes a bounded custom input", () => {
  const changed = vi.fn();
  render(<Editor initial="917" changed={changed} />);
  const exact = screen.getByLabelText("Time limit seconds") as HTMLInputElement;
  expect(exact.value).toBe("917");
  expect(exact.max).toBe("14400");
  expect(changed).not.toHaveBeenCalled();
  fireEvent.change(exact, { target: { value: "5399" } });
  expect(changed).toHaveBeenLastCalledWith("5399");
});

it("choosing Custom preserves the previous value until the user edits it", () => {
  const changed = vi.fn();
  render(<Editor changed={changed} />);
  fireEvent.change(screen.getByLabelText("Time limit"), {
    target: { value: "custom" },
  });
  expect(changed).not.toHaveBeenCalled();
  expect(
    (screen.getByLabelText("Time limit seconds") as HTMLInputElement).value,
  ).toBe("600");
});

it("native selector keys do not navigate the enclosing agent list", () => {
  const parent = vi.fn();
  render(
    <div onKeyDown={parent}>
      <Editor />
    </div>,
  );
  expect(
    fireEvent.keyDown(screen.getByLabelText("Time limit"), {
      key: "ArrowDown",
    }),
  ).toBe(true);
  expect(parent).not.toHaveBeenCalled();
});

it("shows an exact custom duration when refreshed saved data replaces a preset", () => {
  const changed = vi.fn();
  const { rerender } = render(
    <AgentTimeBudget value={600} onChange={changed} />,
  );
  rerender(<AgentTimeBudget value={917} onChange={changed} />);
  expect(
    (screen.getByLabelText("Time limit seconds") as HTMLInputElement).value,
  ).toBe("917");
  expect(changed).not.toHaveBeenCalled();
});
