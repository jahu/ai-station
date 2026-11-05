import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import SpeechEngineFields from "./SpeechEngineFields";

afterEach(cleanup);

it("checks readiness before calling an expressive model unconfigured", () => {
  render(
    <SpeechEngineFields
      engine="fish_s2_pro"
      direction="natural"
      pace="natural"
      onEngine={vi.fn()}
      onDirection={vi.fn()}
      onPace={vi.fn()}
    />,
  );
  expect(screen.getByRole("status").textContent).toContain(
    "Checking expressive speech",
  );
  expect(
    screen.getByRole("option", { name: /Fish S2 Pro/ }).textContent,
  ).toContain("Checking…");
  expect(screen.queryByText(/This expressive model is not ready/)).toBeNull();
});

it("selects an installed checkpoint from the same model control without changing engines twice", () => {
  const onEngine = vi.fn();
  const onModel = vi.fn();
  render(
    <SpeechEngineFields
      engine=""
      direction="natural"
      pace="natural"
      modelId="voice-one"
      models={[{ id: "voice-one", name: "Studio voice", available: true }]}
      onEngine={onEngine}
      onModel={onModel}
      onDirection={vi.fn()}
      onPace={vi.fn()}
    />,
  );
  expect(
    (screen.getByLabelText("Speech model") as HTMLSelectElement).value,
  ).toBe("installed:voice-one");
  fireEvent.change(screen.getByLabelText("Speech model"), {
    target: { value: "installed:voice-one" },
  });
  expect(onModel).toHaveBeenCalledWith("voice-one");
  expect(onEngine).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Speech model"), {
    target: { value: "" },
  });
  expect(onEngine).toHaveBeenCalledWith("");
});
