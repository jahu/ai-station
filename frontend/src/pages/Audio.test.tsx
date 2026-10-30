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
