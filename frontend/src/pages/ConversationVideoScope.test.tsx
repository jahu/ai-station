import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import ConversationVideoScope, {
  type ConversationVideoSettings,
} from "./ConversationVideoScope";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function catalog(portrait = true) {
  const recipe = {
    label: "SVI Pro",
    width: 832,
    height: 480,
    frames: 81,
    fps: 15,
    steps: 20,
    cfg: 5,
    image_required: true,
    memory_mib: 18432,
    resolutions: [
      { width: 832, height: 480 },
      ...(portrait ? [{ width: 480, height: 832 }] : []),
    ],
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => ({
      ok: true,
      json: async () =>
        String(input).endsWith("/video/models")
          ? {
              items: [
                {
                  id: "svi",
                  name: "Continuous video",
                  available: true,
                  operation_recipe: recipe,
                },
              ],
            }
          : { available: true, operation_recipe: recipe },
    })),
  );
}

it("keeps the chosen conversation model and format when changing film duration", async () => {
  catalog();
  let saved: ConversationVideoSettings | null = null;
  const frameRates = vi.fn();
  function Form() {
    const [value, setValue] = useState<ConversationVideoSettings | null>(null);
    saved = value;
    return (
      <ConversationVideoScope
        value={value}
        disabled={false}
        onChange={setValue}
        onFrameRateChange={frameRates}
      />
    );
  }
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Form />
    </QueryClientProvider>,
  );
  await screen.findByRole("option", { name: "Continuous video" });
  fireEvent.change(screen.getByRole("combobox", { name: "Video model" }), {
    target: { value: "svi" },
  });
  await screen.findByRole("option", { name: "Portrait · 480 × 832" });
  fireEvent.change(screen.getByRole("combobox", { name: "Video format" }), {
    target: { value: "480x832" },
  });
  fireEvent.change(screen.getByRole("combobox", { name: "Video length" }), {
    target: { value: "20" },
  });
  expect(saved).toEqual({
    model_id: "svi",
    width: 480,
    height: 832,
    duration_seconds: 20,
    composition_mode: "continuous",
    memory_profile: "default",
  });
  expect(screen.getByText(/Add one original image/)).toBeTruthy();
  await waitFor(() => expect(frameRates).toHaveBeenLastCalledWith(15));
});

it("keeps a saved unsupported format visible and lets the user correct it", async () => {
  catalog(false);
  let saved: ConversationVideoSettings;
  function Form() {
    const [value, setValue] = useState<ConversationVideoSettings | null>({
      model_id: "svi",
      width: 480,
      height: 832,
      duration_seconds: 10,
      composition_mode: "continuous",
    });
    saved = value!;
    return (
      <ConversationVideoScope
        value={value}
        disabled={false}
        onChange={setValue}
        onFrameRateChange={() => {}}
      />
    );
  }
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Form />
    </QueryClientProvider>,
  );
  const choice = await screen.findByRole("combobox", { name: "Video format" });
  expect((choice as HTMLSelectElement).value).toBe("480x832");
  expect((choice as HTMLSelectElement).disabled).toBe(false);
  expect(screen.getByText(/Choose an available video format/)).toBeTruthy();
  fireEvent.change(choice, { target: { value: "832x480" } });
  expect(saved!.width).toBe(832);
  expect(saved!.height).toBe(480);
});
