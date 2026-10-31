import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import SpeechEngineFields from "./SpeechEngineFields";

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
