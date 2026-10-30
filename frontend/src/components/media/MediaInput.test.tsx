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

it("offers compressed recordings only in transcription mode", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => [
        {
          id: "compressed",
          type: "audio",
          mime_type: "audio/mp4",
          original_filename: "meeting.m4a",
          metadata: {},
        },
        {
          id: "long-wave",
          type: "audio",
          mime_type: "audio/wav",
          original_filename: "long.wav",
          metadata: { duration_seconds: 120 },
        },
      ],
    })),
  );
  const onChange = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MediaInput
        kind="audio"
        audioMode="transcription"
        maxAudioSeconds={300}
        label="Recording"
        hint="Recordings"
        value=""
        onChange={onChange}
        disabled={false}
        onBusy={vi.fn()}
      />
    </QueryClientProvider>,
  );
  expect(
    screen.getByLabelText("Upload speech").getAttribute("accept"),
  ).toContain(".m4a");
  fireEvent.click(screen.getByRole("button", { name: "Choose from Library" }));
  const compressed = await screen.findByRole("button", {
    name: "Choose meeting.m4a compress",
  });
  expect(
    screen.getByRole("button", { name: "Choose long.wav long-wav" }),
  ).toBeTruthy();
  fireEvent.click(compressed);
  expect(onChange).toHaveBeenCalledWith("compressed");
});

it("keeps effect tracks out of voice references without hiding them from transcription", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => [
        {
          id: "effects-track",
          type: "audio",
          mime_type: "audio/wav",
          original_filename: "wind.wav",
          metadata: { capability: "audio.effects", duration_seconds: 8 },
        },
        {
          id: "speech-track",
          type: "audio",
          mime_type: "audio/wav",
          original_filename: "voice.wav",
          metadata: { duration_seconds: 8 },
        },
      ],
    })),
  );
  const client = new QueryClient();
  const props = {
    kind: "audio" as const,
    label: "Recording",
    hint: "WAV",
    value: "",
    onChange: vi.fn(),
    disabled: false,
    onBusy: vi.fn(),
  };
  const { rerender } = render(
    <QueryClientProvider client={client}>
      <MediaInput {...props} />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Choose from Library" }));
  await screen.findByRole("button", { name: "Choose voice.wav speech-t" });
  expect(
    screen.queryByRole("button", { name: "Choose wind.wav effects-" }),
  ).toBeNull();
  rerender(
    <QueryClientProvider client={client}>
      <MediaInput {...props} audioMode="transcription" />
    </QueryClientProvider>,
  );
  expect(
    await screen.findByRole("button", { name: "Choose wind.wav effects-" }),
  ).toBeTruthy();
});
