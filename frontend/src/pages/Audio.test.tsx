import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import Audio from "./Audio";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function mount(entry = "/audio") {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/audio" element={<Audio />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
it("keeps speech generation in the workspace with visible progress and stop", async () => {
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      path.endsWith("/hardware")
        ? { gpus: [] }
        : path.includes("/runs")
          ? { id: "speech", status: "queued" }
          : {
              id: "voice",
              original_filename: "reference.wav",
              type: "audio",
              mime_type: "audio/wav",
            },
  }));
  vi.stubGlobal("fetch", fetch);
  mount();
  expect(
    screen
      .getByRole("button", { name: "Generate speech" })
      .hasAttribute("disabled"),
  ).toBe(true);
  fireEvent.change(screen.getByLabelText("Upload speech"), {
    target: {
      files: [new File(["wav"], "reference.wav", { type: "audio/wav" })],
    },
  });
  await screen.findByText("reference.wav");
  fireEvent.change(screen.getByLabelText("Text to speak"), {
    target: { value: "Witaj" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Generate speech" }));
  await screen.findByText("Waiting for an available GPU");
  expect(
    screen
      .getByRole("button", { name: "Generating speech…" })
      .hasAttribute("disabled"),
  ).toBe(true);
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/audio/runs",
      expect.objectContaining({
        body: JSON.stringify({
          text: "Witaj",
          gpu: "auto",
          reference_artifact_id: "voice",
        }),
      }),
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: "Stop generation" }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/runs/speech/cancel",
      expect.objectContaining({ method: "POST" }),
    ),
  );
});
it("reuses the finished speech as the next voice without queueing a Run", async () => {
  const spoken = {
    id: "spoken01",
    type: "audio",
    mime_type: "audio/wav",
    original_filename: "line.wav",
    title: "Spoken line",
  };
  const fetch = vi.fn(async (path: string, options?: RequestInit) => ({
    ok: options === undefined,
    json: async () => {
      const url = String(path);
      if (url.endsWith("/hardware")) return { gpus: [] };
      if (url.endsWith("/lineage"))
        return { id: "spoken01", sources: [], derived: [] };
      if (url.includes("/artifacts?")) return [spoken];
      if (url.includes("/artifacts/")) return spoken;
      if (url.includes("/runs/")) return { id: "done", status: "succeeded" };
      return {};
    },
  }));
  vi.stubGlobal("fetch", fetch);
  mount("/audio?run=done");
  fireEvent.click(
    await screen.findByRole("link", {
      name: "Use as voice reference spoken01",
    }),
  );
  await screen.findByText("Spoken line");
  expect(screen.getByLabelText("Generated audio")).toBeTruthy();
  expect(
    screen
      .getByRole("button", { name: "Generate speech" })
      .hasAttribute("disabled"),
  ).toBe(true);
  expect(fetch.mock.calls.every((call) => !call[1])).toBe(true);
});

it("sends real delivery controls only after opting in, without changing narration", async () => {
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      path.endsWith("/audio/capabilities")
        ? { delivery: { version: "chatterbox-controls-v1" } }
        : path.endsWith("/hardware")
          ? { gpus: [] }
          : path.includes("/runs")
            ? { id: "speech", status: "queued" }
            : {
                id: "voice",
                original_filename: "reference.wav",
                type: "audio",
                mime_type: "audio/wav",
              },
  }));
  vi.stubGlobal("fetch", fetch);
  mount("/audio?input=voice");
  fireEvent.click(
    await screen.findByRole("checkbox", { name: /Shape the delivery/ }),
  );
  fireEvent.change(screen.getByLabelText("Expression"), {
    target: { value: "1.1" },
  });
  fireEvent.change(screen.getByLabelText("Voice guidance"), {
    target: { value: "0.25" },
  });
  fireEvent.change(screen.getByLabelText("Voice variation"), {
    target: { value: "0.7" },
  });
  fireEvent.change(screen.getByLabelText("Text to speak"), {
    target: { value: "Witaj. To dokładnie moje słowa." },
  });
  fireEvent.click(screen.getByRole("button", { name: "Generate speech" }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/audio/runs",
      expect.objectContaining({
        body: JSON.stringify({
          text: "Witaj. To dokładnie moje słowa.",
          gpu: "auto",
          reference_artifact_id: "voice",
          delivery: { exaggeration: 1.1, cfg_weight: 0.25, temperature: 0.7 },
        }),
      }),
    ),
  );
});

it("turning delivery off restores the original speech request", async () => {
  const writes: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      if (path === "/api/audio/runs" && init?.method === "POST")
        writes.push(JSON.parse(String(init.body)));
      return {
        ok: true,
        json: async () =>
          path.endsWith("/audio/capabilities")
            ? { delivery: { version: "chatterbox-controls-v1" } }
            : path.endsWith("/hardware")
              ? { gpus: [] }
              : path.includes("/runs")
                ? { id: "speech", status: "queued" }
                : {
                    id: "voice",
                    type: "audio",
                    mime_type: "audio/wav",
                    original_filename: "reference.wav",
                  },
      };
    }),
  );
  mount("/audio?input=voice");
  const toggle = await screen.findByRole("checkbox", {
    name: /Shape the delivery/,
  });
  fireEvent.click(toggle);
  fireEvent.change(screen.getByLabelText("Expression"), {
    target: { value: "1.2" },
  });
  fireEvent.click(toggle);
  expect(screen.queryByLabelText("Expression")).toBeNull();
  fireEvent.change(screen.getByLabelText("Text to speak"), {
    target: { value: "Witaj" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Generate speech" }));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0]).toEqual({
    text: "Witaj",
    gpu: "auto",
    reference_artifact_id: "voice",
  });
});

it("chooses expressive speech and sends voice direction without Chatterbox controls", async () => {
  const writes: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      if (path === "/api/audio/runs" && init?.method === "POST")
        writes.push(JSON.parse(String(init.body)));
      return {
        ok: true,
        json: async () =>
          path.endsWith("/audio/capabilities")
            ? {
                delivery: { version: "chatterbox-controls-v1" },
                engines: {
                  fish_s2_pro: {
                    available: true,
                    readiness: "ready",
                    license_url: "https://huggingface.co/fishaudio/s2-pro",
                  },
                },
              }
            : path.endsWith("/hardware")
              ? { gpus: [] }
              : path.includes("/runs")
                ? { id: "speech", status: "queued" }
                : {
                    id: "voice",
                    type: "audio",
                    mime_type: "audio/wav",
                    original_filename: "voice.wav",
                  },
      };
    }),
  );
  mount("/audio?input=voice");
  fireEvent.click(
    await screen.findByRole("checkbox", { name: /Shape the delivery/ }),
  );
  fireEvent.change(screen.getByLabelText("Expression"), {
    target: { value: "1.1" },
  });
  fireEvent.change(screen.getByRole("combobox", { name: "Speech model" }), {
    target: { value: "fish_s2_pro" },
  });
  expect(screen.queryByLabelText("Expression")).toBeNull();
  fireEvent.change(screen.getByRole("combobox", { name: "Voice direction" }), {
    target: { value: "whisper" },
  });
  fireEvent.change(screen.getByRole("combobox", { name: "Speaking pace" }), {
    target: { value: "slow" },
  });
  fireEvent.change(screen.getByLabelText("Text to speak"), {
    target: { value: "To są dokładne słowa." },
  });
  fireEvent.click(screen.getByRole("button", { name: "Generate speech" }));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0]).toEqual({
    text: "To są dokładne słowa.",
    gpu: "auto",
    reference_artifact_id: "voice",
    engine: "fish_s2_pro",
    direction: "whisper",
    pace: "slow",
  });
});

it("keeps an unconfigured expressive engine unavailable instead of inventing readiness", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => ({
      ok: true,
      json: async () =>
        path.endsWith("/audio/capabilities")
          ? {
              engines: {
                fish_s2_pro: { available: false, readiness: "unavailable" },
              },
            }
          : path.endsWith("/hardware")
            ? { gpus: [] }
            : { id: "voice", type: "audio", mime_type: "audio/wav" },
    })),
  );
  mount();
  const option = await screen.findByRole("option", {
    name: "Fish S2 Pro · Expressive · Not configured",
  });
  expect(option.hasAttribute("disabled")).toBe(true);
  expect(
    (
      screen.getByRole("combobox", {
        name: "Speech model",
      }) as HTMLSelectElement
    ).value,
  ).toBe("");
});

it("prepares phone references with Fish and clears an incompatible reference when switching models", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => ({
      ok: true,
      json: async () =>
        path.endsWith("/audio/capabilities")
          ? {
              available: true,
              engines: { fish_s2_pro: { available: true, readiness: "ready" } },
            }
          : path.endsWith("/hardware")
            ? { gpus: [] }
            : {
                id: "phone",
                type: "audio",
                mime_type: "audio/mp4",
                original_filename: "voice.m4a",
              },
    })),
  );
  mount();
  const model = await screen.findByRole("combobox", { name: "Speech model" });
  await screen.findByRole("option", { name: "Fish S2 Pro · Expressive" });
  fireEvent.change(model, { target: { value: "fish_s2_pro" } });
  expect(
    screen.getByLabelText("Upload speech").getAttribute("accept"),
  ).toContain(".m4a");
  fireEvent.change(screen.getByLabelText("Upload speech"), {
    target: {
      files: [new File(["voice"], "voice.m4a", { type: "audio/mp4" })],
    },
  });
  await screen.findByText("voice.m4a");
  fireEvent.change(model, { target: { value: "" } });
  expect(screen.queryByText("voice.m4a")).toBeNull();
  expect(screen.getByLabelText("Upload speech").getAttribute("accept")).toBe(
    "audio/wav,.wav",
  );
});

it("generates an expressive voice without uploading a recording and keeps recording mode explicit", async () => {
  const writes: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      if (path === "/api/audio/runs" && init?.method === "POST")
        writes.push(JSON.parse(String(init.body)));
      return {
        ok: true,
        json: async () =>
          path.endsWith("/audio/capabilities")
            ? {
                engines: {
                  fish_s2_pro: {
                    available: true,
                    readiness: "ready",
                    voice_sources: ["reference", "model"],
                  },
                },
              }
            : path.endsWith("/hardware")
              ? { gpus: [] }
              : path.includes("/runs")
                ? { id: "speech", status: "queued" }
                : [],
      };
    }),
  );
  mount("/audio?engine=fish_s2_pro");
  const source = await screen.findByRole("combobox", { name: "Voice source" });
  expect((source as HTMLSelectElement).value).toBe("model");
  expect(screen.queryByText("Voice reference")).toBeNull();
  fireEvent.change(screen.getByLabelText("Text to speak"), {
    target: { value: "Dokładne słowa." },
  });
  const submit = screen.getByRole("button", { name: "Generate speech" });
  await waitFor(() =>
    expect((submit as HTMLButtonElement).disabled).toBe(false),
  );
  fireEvent.change(source, { target: { value: "reference" } });
  expect(screen.getByText("Voice reference")).toBeTruthy();
  expect((submit as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(source, { target: { value: "model" } });
  fireEvent.click(submit);
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0]).toEqual({
    text: "Dokładne słowa.",
    gpu: "auto",
    reference_artifact_id: null,
    engine: "fish_s2_pro",
    voice_source: "model",
    direction: "natural",
    pace: "natural",
  });
});

it("uses an installed speech model from its preparation link despite unavailable default speech", async () => {
  const id = "cf567bf6-cd46-4102-992a-e7913c404f06";
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      path === "/api/audio/models"
        ? { items: [{ id, name: "Installed studio voice", available: true }] }
        : path.includes(`/audio/models/${id}/capabilities`)
          ? { available: true, configuration_source: "managed" }
          : path.endsWith("/capabilities")
            ? { available: false }
            : path.endsWith("/hardware")
              ? { gpus: [] }
              : path.includes("/runs")
                ? { id: "selected-speech", status: "queued" }
                : {
                    id: "voice",
                    original_filename: "voice.wav",
                    type: "audio",
                    mime_type: "audio/wav",
                  },
  }));
  vi.stubGlobal("fetch", fetch);
  mount(`/audio?model=${id}&input=voice`);
  await screen.findByRole("option", { name: "Installed studio voice" });
  expect(
    (screen.getByLabelText("Speech model") as HTMLSelectElement).value,
  ).toBe(`installed:${id}`);
  fireEvent.change(screen.getByLabelText("Text to speak"), {
    target: { value: "Dzień dobry" },
  });
  await waitFor(() =>
    expect(
      (
        screen.getByRole("button", {
          name: "Generate speech",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false),
  );
  fireEvent.click(screen.getByRole("button", { name: "Generate speech" }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/audio/runs",
      expect.objectContaining({
        body: JSON.stringify({
          text: "Dzień dobry",
          gpu: "auto",
          reference_artifact_id: "voice",
          model_id: id,
        }),
      }),
    ),
  );
});

it("sends an explicit English language only when the selected engine supports it", async () => {
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      path.endsWith("/audio/capabilities")
        ? { available: true, languages: ["pl", "en"] }
        : path.endsWith("/hardware")
          ? { gpus: [] }
          : path.includes("/runs")
            ? { id: "speech", status: "queued" }
            : {
                id: "voice",
                original_filename: "reference.wav",
                type: "audio",
                mime_type: "audio/wav",
              },
  }));
  vi.stubGlobal("fetch", fetch);
  mount("/audio?input=voice");
  await waitFor(() =>
    expect(
      (screen.getByRole("option", { name: "English" }) as HTMLOptionElement)
        .disabled,
    ).toBe(false),
  );
  fireEvent.change(screen.getByLabelText("Spoken language"), {
    target: { value: "en" },
  });
  fireEvent.change(screen.getByLabelText("Text to speak"), {
    target: { value: "Hello there." },
  });
  fireEvent.click(screen.getByRole("button", { name: "Generate speech" }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/audio/runs",
      expect.objectContaining({
        body: JSON.stringify({
          text: "Hello there.",
          language: "en",
          gpu: "auto",
          reference_artifact_id: "voice",
        }),
      }),
    ),
  );
});
