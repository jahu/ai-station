import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { effectsScopeReady } from "./assistant-options";
import ConversationEffectsScope, {
  type EffectsOptions,
} from "./ConversationEffectsScope";
afterEach(cleanup);

it("requires an explicit source or a nonempty new-film description without blocking Auto references", () => {
  expect(
    effectsScopeReady({
      action: "audio.effects",
      effects: { video_artifact_id: null },
    }),
  ).toBe(false);
  expect(
    effectsScopeReady({
      action: "audio.effects",
      effects: { video_artifact_id: "film" },
    }),
  ).toBe(true);
  expect(
    effectsScopeReady({
      action: "video.generate",
      effects: { video_artifact_id: null, prompt: " " },
    }),
  ).toBe(false);
  expect(
    effectsScopeReady({
      action: "video.generate",
      effects: { video_artifact_id: null, prompt: "Birds" },
    }),
  ).toBe(true);
  expect(effectsScopeReady({ action: "auto" })).toBe(true);
});

it("retains description and independent levels when changing the new-film mix policy", () => {
  let saved: EffectsOptions = {
    video_artifact_id: null,
    prompt: "Rain",
    original_gain: 0.8,
    effects_gain: 0.4,
  };
  function Scope() {
    const [value, setValue] = useState(saved);
    saved = value;
    return (
      <ConversationEffectsScope
        newFilm
        frames={360}
        value={value}
        onChange={setValue}
        disabled={false}
        onBusy={() => {}}
      />
    );
  }
  render(<Scope />);
  fireEvent.change(screen.getByRole("combobox", { name: "Film sound mix" }), {
    target: { value: "replace" },
  });
  expect(saved.preview_mode).toBe("replace");
  expect(saved.prompt).toBe("Rain");
  fireEvent.change(screen.getByRole("combobox", { name: "Film sound mix" }), {
    target: { value: "mix" },
  });
  expect(saved.original_gain).toBe(0.8);
  expect(saved.effects_gain).toBe(0.4);
  fireEvent.change(
    screen.getByRole("slider", { name: "New film effects level" }),
    { target: { value: "0.45" } },
  );
  expect(saved.effects_gain).toBe(0.45);
});
