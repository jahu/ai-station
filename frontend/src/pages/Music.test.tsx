import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import Audio from "./Audio";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

function mount(entry = "/audio?mode=music") {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={[entry]}>
        <Audio />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function responses(available = true) {
  let stopped = false;
  return vi.fn(async (path: string, options?: RequestInit) => ({
    ok: true,
    json: async () => {
      if (path.endsWith("/capabilities"))
        return { available, max_seconds: 600 };
      if (path.endsWith("/hardware"))
        return { gpus: [{ index: 7, name: "Test GPU" }] };
      if (path.endsWith("/cancel")) stopped = true;
      if (path.includes("/artifacts?")) return [];
      return {
        id: "music-run",
        capability: "audio.music",
        status: stopped ? "canceled" : "queued",
        requested_gpu: "auto",
        parameters: options?.body ? JSON.parse(String(options.body)) : {},
      };
    },
  }));
}

it("shows music readiness without pretending an unavailable engine can generate", async () => {
  const fetch = responses(false);
  vi.stubGlobal("fetch", fetch);
  mount();
  await screen.findByText(/Local music is not ready/);
  expect(
    screen
      .getByRole("button", { name: "Generate music" })
      .hasAttribute("disabled"),
  ).toBe(true);
  expect(
    screen.getByRole("heading", { name: "Set the mood. Find your sound." }),
  ).toBeTruthy();
  expect(fetch.mock.calls.every((call) => !call[1]?.method)).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Create speech" }));
  expect(
    screen.getByRole("heading", { name: "Give your words a voice." }),
  ).toBeTruthy();
});

it("generates music with lyrics in the shared workspace and exposes Stop", async () => {
  const fetch = responses();
  vi.stubGlobal("fetch", fetch);
  mount();
  await waitFor(() =>
    expect(
      screen
        .getByRole("button", { name: "Generate music" })
        .hasAttribute("disabled"),
    ).toBe(true),
  );
  fireEvent.change(screen.getByLabelText("Describe your music"), {
    target: { value: "Acoustic folk, warm vocals" },
  });
  fireEvent.click(screen.getByRole("button", { name: "With lyrics" }));
  fireEvent.change(screen.getByLabelText("Your lyrics"), {
    target: { value: "[Verse]\nA quiet morning" },
  });
  fireEvent.change(screen.getByLabelText("Music length"), {
    target: { value: "120" },
  });
  await waitFor(() =>
    expect(
      screen
        .getByRole("button", { name: "Generate music" })
        .hasAttribute("disabled"),
    ).toBe(false),
  );
  fireEvent.click(screen.getByRole("button", { name: "Generate music" }));
  await screen.findByText("Waiting for an available GPU and enough memory");
  const sent = fetch.mock.calls.find(
    ([path]) => path === "/api/audio/music/runs",
  );
  expect(JSON.parse(String(sent?.[1]?.body))).toEqual(
    expect.objectContaining({
      caption: "Acoustic folk, warm vocals",
      lyrics: "[Verse]\nA quiet morning",
      instrumental: false,
      duration_seconds: 120,
      gpu: "auto",
      seed: null,
      client_request_id: expect.stringMatching(/^[0-9a-f-]{36}$/),
    }),
  );
  expect(
    screen
      .getByRole("button", { name: "Create speech" })
      .hasAttribute("disabled"),
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Stop generation" }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/runs/music-run/cancel",
      expect.objectContaining({ method: "POST" }),
    ),
  );
});

it("reuses the same request identity after an uncertain response", async () => {
  const normal = responses();
  const submitted: string[] = [];
  const fetch = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/audio/music/runs") {
      submitted.push(JSON.parse(String(options?.body)).client_request_id);
      if (submitted.length === 1) throw new TypeError("Connection interrupted");
    }
    return normal(path, options);
  });
  vi.stubGlobal("fetch", fetch);
  mount();
  fireEvent.change(screen.getByLabelText("Describe your music"), {
    target: { value: "Ambient piano" },
  });
  await waitFor(() =>
    expect(
      screen
        .getByRole("button", { name: "Generate music" })
        .hasAttribute("disabled"),
    ).toBe(false),
  );
  fireEvent.click(screen.getByRole("button", { name: "Generate music" }));
  await screen.findByText("Connection interrupted");
  fireEvent.click(screen.getByRole("button", { name: "Generate music" }));
  await screen.findByText("Waiting for an available GPU and enough memory");
  expect(submitted).toHaveLength(2);
  expect(submitted[0]).toBe(submitted[1]);
});

it("restores music mode from a saved Run without asking the speech form for a voice", async () => {
  const normal = responses();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, options?: RequestInit) => {
      if (path === "/api/runs/saved")
        return {
          ok: true,
          json: async () => ({
            id: "saved",
            capability: "audio.music",
            status: "succeeded",
            requested_gpu: "auto",
            parameters: {
              caption: "Quiet guitar",
              instrumental: true,
              duration_seconds: 60,
              seed: 17,
            },
          }),
        };
      return normal(path, options);
    }),
  );
  mount("/audio?run=saved");
  await screen.findByDisplayValue("Quiet guitar");
  expect(
    (screen.getByLabelText("Music length") as HTMLSelectElement).value,
  ).toBe("60");
  expect(
    screen.getByRole("button", { name: "Music", pressed: true }),
  ).toBeTruthy();
  expect(screen.queryByLabelText("Upload speech")).toBeNull();
});
