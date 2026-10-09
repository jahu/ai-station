import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import MediaInput from "./MediaInput";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("moves through inline Library files with arrow keys", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => [
        {
          id: "voiceone",
          original_filename: "alpha.wav",
          type: "audio",
          mime_type: "audio/wav",
        },
        {
          id: "voicetwo",
          original_filename: "bravo.wav",
          type: "audio",
          mime_type: "audio/wav",
        },
      ],
    })),
  );
  const onChange = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MediaInput
        kind="audio"
        label="Voice reference"
        hint="WAV"
        value=""
        onChange={onChange}
        disabled={false}
        onBusy={vi.fn()}
      />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Choose from Library" }));
  const first = await screen.findByRole("button", {
    name: "Choose alpha.wav voiceone",
  });
  const second = screen.getByRole("button", {
    name: "Choose bravo.wav voicetwo",
  });
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(
    screen.getByRole("region", { name: "Reusable recordings" }),
  ).toBeTruthy();
  fireEvent.keyDown(first.closest(".media-picker-list") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  expect(document.activeElement).toBe(second);
  fireEvent.keyDown(second.closest(".media-picker-list") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
  fireEvent.click(first);
  expect(onChange).toHaveBeenCalledWith("voiceone");
});
