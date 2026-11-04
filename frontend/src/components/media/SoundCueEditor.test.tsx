import { useState } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import SoundCueEditor from "./SoundCueEditor";
import { cuesValid, type SoundCue } from "./sound-cues";

afterEach(cleanup);

function Form() {
  const [cues, setCues] = useState<SoundCue[]>([]);
  return (
    <>
      <SoundCueEditor
        fps={24}
        frames={240}
        value={cues}
        onChange={setCues}
        disabled={false}
      />
      <button disabled={!cuesValid(cues, 240)}>Generate</button>
    </>
  );
}

it("edits frame-aligned scene directions and prevents missing descriptions or overlap", () => {
  render(<Form />);
  fireEvent.click(screen.getByText(/Change sounds over time/));
  fireEvent.click(screen.getByRole("button", { name: "Add scene direction" }));
  expect(
    screen.getByRole("button", { name: "Generate" }).hasAttribute("disabled"),
  ).toBe(true);
  fireEvent.change(screen.getByLabelText("Scene 1 sound description"), {
    target: { value: "Bells" },
  });
  fireEvent.change(screen.getByLabelText("Scene 1 end in seconds"), {
    target: { value: "2.5" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Add scene direction" }));
  expect(
    (screen.getByLabelText("Scene 2 start in seconds") as HTMLInputElement)
      .value,
  ).toBe("2.5");
  fireEvent.change(screen.getByLabelText("Scene 2 sound description"), {
    target: { value: "Birds" },
  });
  expect(
    screen.getByRole("button", { name: "Generate" }).hasAttribute("disabled"),
  ).toBe(false);
  fireEvent.change(screen.getByLabelText("Scene 2 start in seconds"), {
    target: { value: "1" },
  });
  expect(screen.getByRole("alert")).toBeTruthy();
  expect(
    screen.getByRole("button", { name: "Generate" }).hasAttribute("disabled"),
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Remove sound cue 2" }));
  expect(screen.queryByRole("alert")).toBeNull();
  expect(
    screen.getByRole("button", { name: "Generate" }).hasAttribute("disabled"),
  ).toBe(false);
});
