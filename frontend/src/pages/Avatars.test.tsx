import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import Avatars from "./Avatars";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function mount(entry = "/avatars") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/avatars" element={<Avatars />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}

function wholeRuntime(checking = false) {
  const writes: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, options?: RequestInit) => {
      const input = {
        id: path.endsWith("portrait") ? "portrait" : "speech",
        type: path.endsWith("portrait") ? "image" : "audio",
        mime_type: path.endsWith("portrait") ? "image/png" : "audio/wav",
        original_filename: "Input",
      };
      const job = {
        task_id: "whole-task",
        revision: 1,
        kind: "avatar",
        mode: "whole_recording",
        status: "queued",
        active_run_ids: ["whole-run"],
        total_segments: 0,
        completed_segments: 0,
        total_stages: 1,
        completed_stages: 0,
        final_artifact_id: null,
        duration_seconds: 40.08,
        resume_allowed: false,
        error_message: "",
      };
      if (options?.method === "POST")
        writes.push(JSON.parse(String(options.body)));
      return {
        ok: true,
        json: async () =>
          path.endsWith("whole-capabilities")
            ? {
                available: !checking,
                backend: "sonic",
                readiness: checking ? "checking" : "ready",
              }
            : path.endsWith("capabilities")
              ? { available: true }
              : path.endsWith("hardware")
                ? { gpus: [] }
                : path.includes("/media/jobs")
                  ? job
                  : path.includes("/runs")
                    ? {
                        id: "echo-run",
                        status: "queued",
                        parameters: {},
                        metadata: {},
                        executor_type: "echomimic",
                      }
                    : input,
      };
    }),
  );
  return writes;
}

it("defaults new full recordings to stable detail and sends only applicable controls", async () => {
  const writes = wholeRuntime();
  mount("/avatars?image=portrait&audio=speech");
  await screen.findByRole("region", { name: "High-detail avatar quality" });
  expect(screen.queryByLabelText("Scene and motion")).toBeNull();
  expect(
    screen.queryByRole("checkbox", { name: /Improve my prompt locally/ }),
  ).toBeNull();
  expect(screen.queryByLabelText("Quality 384")).toBeNull();
  const generate = screen.getByRole("button", {
    name: "Generate avatar video",
  });
  await vi.waitFor(() => expect(generate.hasAttribute("disabled")).toBe(false));
  fireEvent.click(generate);
  await vi.waitFor(() => expect(writes.length).toBe(1));
  expect(writes[0]).toEqual(
    expect.objectContaining({
      image_artifact_id: "portrait",
      audio_artifact_id: "speech",
      generation_profile: "sonic_whole_768_v1",
      seed: 43,
      gpu: "auto",
    }),
  );
  expect(writes[0]).not.toHaveProperty("steps");
  expect(writes[0]).not.toHaveProperty("size");
  expect(writes[0]).not.toHaveProperty("memory_profile");
  expect(writes[0]).not.toHaveProperty("translation");
});

it("sends local enhancement only for an Echo descriptive prompt", async () => {
  const writes = wholeRuntime();
  mount("/avatars?image=portrait&audio=speech");
  await screen.findByRole("region", { name: "High-detail avatar quality" });
  fireEvent.click(screen.getByLabelText("Full recording (up to 60 seconds)"));
  fireEvent.click(
    await screen.findByRole("checkbox", { name: /Improve my prompt locally/ }),
  );
  const generate = screen.getByRole("button", {
    name: "Generate avatar video",
  });
  await vi.waitFor(() => expect(generate.hasAttribute("disabled")).toBe(false));
  fireEvent.click(generate);
  await vi.waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0]).toMatchObject({
    translation: {
      mode: "off",
      enhance: true,
      review: false,
      protected_terms: [],
    },
  });
  expect(writes[0]).not.toHaveProperty("generation_profile");
});

it("keeps high-detail submission disabled during verification instead of switching to Echo", async () => {
  const writes = wholeRuntime(true);
  mount("/avatars?image=portrait&audio=speech");
  await screen.findByText("Checking the installed model files…");
  expect(
    screen
      .getByRole("button", { name: "Generate avatar video" })
      .hasAttribute("disabled"),
  ).toBe(true);
  expect(screen.queryByLabelText("Quality 384")).toBeNull();
  expect(writes).toHaveLength(0);
});
it("selects existing inputs, queues video and keeps the live result beside the form", async () => {
  const artifacts = [
    {
      id: "portrait",
      type: "image",
      mime_type: "image/png",
      original_filename: "Portrait.png",
    },
    {
      id: "speech",
      type: "audio",
      mime_type: "audio/wav",
      original_filename: "Speech.wav",
    },
  ];
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      path.endsWith("/capabilities")
        ? { available: true }
        : path.endsWith("/hardware")
          ? { gpus: [] }
          : path.includes("/runs")
            ? { id: "avatar", status: "queued" }
            : path.endsWith("/artifacts")
              ? artifacts
              : artifacts.find((a) => path.endsWith(a.id)),
  }));
  vi.stubGlobal("fetch", fetch);
  mount();
  fireEvent.click(screen.getByLabelText("Full recording (up to 60 seconds)"));
  fireEvent.click(
    screen.getAllByRole("button", { name: "Choose from Library" })[0],
  );
  fireEvent.click(
    await within(
      screen.getByRole("region", { name: "Portrait library" }),
    ).findByRole(
      "button",
      { name: "Choose Portrait.png portrait" },
      { timeout: 5000 },
    ),
  );
  fireEvent.click(
    screen.getAllByRole("button", { name: "Choose from Library" })[1],
  );
  fireEvent.click(
    await within(
      screen.getByRole("region", { name: "Speech recording library" }),
    ).findByRole("button", { name: "Choose Speech.wav speech" }),
  );
  const qualityList = screen
    .getByLabelText("Quality 384")
    .closest(".avatar-quality-choice-list") as HTMLElement;
  fireEvent.keyDown(qualityList, { key: "Home" });
  fireEvent.keyDown(qualityList, { key: "Enter" });
  await vi.waitFor(() =>
    expect(
      screen
        .getByRole("button", { name: "Generate avatar video" })
        .hasAttribute("disabled"),
    ).toBe(false),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Generate avatar video" }),
  );
  await screen.findByText("Waiting for an available GPU");
  expect(fetch).toHaveBeenCalledWith(
    "/api/avatars/runs",
    expect.objectContaining({
      body: JSON.stringify({
        image_artifact_id: "portrait",
        audio_artifact_id: "speech",
        prompt: "A person speaking naturally, static camera.",
        size: 256,
        frames: 81,
        steps: 8,
        seed: 43,
        gpu: "auto",
      }),
    }),
  );
});
it("restores a completed video from the workspace URL", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => ({
      ok: true,
      json: async () =>
        path.endsWith("/lineage")
          ? { id: "movie", sources: [], derived: [] }
          : path.includes("/artifacts?")
            ? [{ id: "movie", type: "video" }]
            : path.includes("/runs/")
              ? { id: "done", status: "succeeded" }
              : { gpus: [] },
    })),
  );
  mount("/avatars?run=done");
  const video = await screen.findByLabelText("Generated video");
  expect(video.getAttribute("src")).toBe("/api/artifacts/movie/file");
  expect(
    screen.getByRole("link", { name: "Open in Library" }).getAttribute("href"),
  ).toBe("/library/movie");
});
it("stages a portrait and speech from the URL without queueing a Run", async () => {
  const artifacts = [
    {
      id: "portrait",
      type: "image",
      mime_type: "image/png",
      original_filename: "Portrait.png",
    },
    {
      id: "speech",
      type: "audio",
      mime_type: "audio/wav",
      original_filename: "Speech.wav",
    },
  ];
  const fetch = vi.fn(async (path: string, options?: RequestInit) => ({
    ok: options === undefined,
    json: async () => {
      const url = String(path);
      if (url.endsWith("/capabilities")) return { available: true };
      if (url.endsWith("/hardware")) return { gpus: [] };
      return artifacts.find((artifact) => url.endsWith(artifact.id)) ?? {};
    },
  }));
  vi.stubGlobal("fetch", fetch);
  mount("/avatars?image=portrait&audio=speech");
  await screen.findByText("Portrait.png");
  await screen.findByText("Speech.wav");
  expect(
    screen
      .getByRole("button", { name: "Generate avatar video" })
      .hasAttribute("disabled"),
  ).toBe(false);
  expect(fetch.mock.calls.every((call) => !call[1])).toBe(true);
});

it("queues typed speech with a voice reference while keeping recording mode unchanged", async () => {
  const artifacts = [
    {
      id: "portrait",
      type: "image",
      mime_type: "image/png",
      original_filename: "Portrait.png",
    },
    {
      id: "voice",
      type: "audio",
      mime_type: "audio/wav",
      original_filename: "Voice.wav",
    },
  ];
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () => {
      if (path.endsWith("/capabilities")) return { available: true };
      if (path.endsWith("/hardware")) return { gpus: [] };
      if (path.includes("/runs")) return { id: "speech", status: "queued" };
      if (path.endsWith("/artifacts")) return artifacts;
      return artifacts.find((a) => path.endsWith(a.id));
    },
  }));
  vi.stubGlobal("fetch", fetch);
  mount("/avatars?image=portrait&audio=voice");
  fireEvent.click(screen.getByLabelText("Full recording (up to 60 seconds)"));
  expect(screen.queryByLabelText("Words to say")).toBeNull();
  fireEvent.click(screen.getByLabelText("Type what to say"));
  expect(screen.getByText("Voice reference")).toBeTruthy();
  expect(
    screen
      .getByRole("button", { name: "Generate avatar video" })
      .hasAttribute("disabled"),
  ).toBe(true);
  fireEvent.change(screen.getByLabelText("Words to say"), {
    target: { value: "Cześć!" },
  });
  await vi.waitFor(() =>
    expect(
      screen
        .getByRole("button", { name: "Generate avatar video" })
        .hasAttribute("disabled"),
    ).toBe(false),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Generate avatar video" }),
  );
  await screen.findByText("Waiting for an available GPU");
  expect(fetch).toHaveBeenCalledWith(
    "/api/avatars/runs",
    expect.objectContaining({
      body: expect.stringContaining('"speech_text":"Cześć!"'),
    }),
  );
  expect(fetch).toHaveBeenCalledWith(
    "/api/avatars/runs",
    expect.objectContaining({
      body: expect.stringContaining('"audio_artifact_id":"voice"'),
    }),
  );
});

it("restores a speech-to-avatar workflow and stops its active animation", async () => {
  const first = {
    id: "speech",
    capability: "audio.speech",
    status: "succeeded",
    parameters: { avatar_after_speech: {} },
  };
  const child = {
    id: "animate",
    capability: "avatar.animate",
    status: "queued",
    parameters: {},
  };
  const fetch = vi.fn(async (path: string, options?: RequestInit) => ({
    ok: true,
    json: async () => {
      if (path.endsWith("/workflow")) return { steps: [first, child] };
      if (path.includes("/artifacts?")) return [];
      if (path.endsWith("/capabilities")) return { available: true };
      if (path.endsWith("/hardware")) return { gpus: [] };
      if (options?.method === "POST") return child;
      return first;
    },
  }));
  vi.stubGlobal("fetch", fetch);
  mount("/avatars?run=speech");
  await screen.findByRole("list", { name: "Avatar workflow" });
  expect(
    screen.getByRole("link", { name: "1. Speech" }).getAttribute("href"),
  ).toBe("/runs/speech");
  expect(
    screen
      .getByRole("link", { name: "2. Animate portrait" })
      .getAttribute("href"),
  ).toBe("/runs/animate");
  fireEvent.click(screen.getByRole("button", { name: "Stop generation" }));
  await vi.waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/runs/animate/cancel",
      expect.objectContaining({ method: "POST" }),
    ),
  );
  expect(
    fetch.mock.calls.some(([url]) => url === "/api/runs/speech/cancel"),
  ).toBe(false);
});

it("defaults to the complete recording and restores its durable job", async () => {
  const fetch = vi.fn(async (path: string, init?: RequestInit) => ({
    ok: true,
    json: async () => {
      if (init?.method === "POST") expect(path).toBe("/api/media/jobs/avatar");
      if (path.endsWith("/capabilities")) return { available: true };
      if (path.endsWith("/hardware")) return { gpus: [] };
      if (path.includes("/media/jobs"))
        return {
          task_id: "whole-recording",
          revision: 1,
          kind: "avatar",
          mode: "continuous",
          status: "queued",
          duration_seconds: 30,
          total_segments: 12,
          completed_segments: 0,
          active_run_ids: ["segment"],
          final_artifact_id: null,
          resume_allowed: false,
          error_message: "",
        };
      return {
        id: path.endsWith("portrait") ? "portrait" : "speech",
        type: path.endsWith("portrait") ? "image" : "audio",
        mime_type: path.endsWith("portrait") ? "image/png" : "audio/wav",
      };
    },
  }));
  vi.stubGlobal("fetch", fetch);
  mount("/avatars?image=portrait&audio=speech");
  expect(
    (
      screen.getByLabelText(
        "Full recording (up to 60 seconds)",
      ) as HTMLInputElement
    ).checked,
  ).toBe(true);
  await vi.waitFor(() =>
    expect(
      screen
        .getByRole("button", { name: "Generate avatar video" })
        .hasAttribute("disabled"),
    ).toBe(false),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Generate avatar video" }),
  );
  await screen.findByText("Your talking avatar");
  const request = fetch.mock.calls.find(
    ([url, init]) =>
      url === "/api/media/jobs/avatar" && init?.method === "POST",
  );
  expect(request).toBeTruthy();
  const body = JSON.parse(String(request![1]!.body));
  expect(body.client_request_id).toMatch(/^[0-9a-f-]{36}$/);
  expect(body.frames).toBeUndefined();
  expect(body.image_artifact_id).toBe("portrait");
  expect(screen.getByText("0 of 12 segments complete")).toBeTruthy();
});

it("restores the saved full-avatar inputs and settings from a job URL without running work", async () => {
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    expect(init?.method).not.toBe("POST");
    return {
      ok: true,
      json: async () =>
        url.includes("/media/jobs/")
          ? {
              task_id: "saved",
              revision: 1,
              kind: "avatar",
              mode: "continuous",
              status: "succeeded",
              duration_seconds: 5,
              completed_segments: 2,
              total_segments: 2,
              active_run_ids: [],
              resume_allowed: false,
              error_message: "",
              final_artifact_id: null,
              request: {
                image_artifact_id: "portrait",
                audio_artifact_id: "voice",
                speech_text: "Saved words",
                prompt: "Saved motion",
                size: 512,
                steps: 12,
                seed: 99,
                gpu: "auto",
              },
            }
          : url.endsWith("/hardware")
            ? { gpus: [] }
            : {
                id: url.endsWith("portrait") ? "portrait" : "voice",
                type: url.endsWith("portrait") ? "image" : "audio",
                mime_type: url.endsWith("portrait") ? "image/png" : "audio/wav",
                original_filename: url.endsWith("portrait")
                  ? "Saved portrait.png"
                  : "Saved voice.wav",
              },
    };
  });
  vi.stubGlobal("fetch", fetch);
  mount("/avatars?job=saved");
  expect(
    ((await screen.findByLabelText("Words to say")) as HTMLTextAreaElement)
      .value,
  ).toBe("Saved words");
  expect(
    (screen.getByLabelText("Scene and motion") as HTMLTextAreaElement).value,
  ).toBe("Saved motion");
  await screen.findByText("Saved portrait.png");
  await screen.findByText("Saved voice.wav");
  expect(
    (
      screen
        .getByLabelText("Quality 512")
        .querySelector("input") as HTMLInputElement
    ).checked,
  ).toBe(true);
});

type SetupProfile = { available: boolean; reason?: string };
function setupFetch(profile: () => Promise<SetupProfile>, ok = true) {
  const fetch = vi.fn(async (path: string, options?: RequestInit) => ({
    ok: !path.endsWith("/capabilities") || ok,
    json: async () => {
      if (path.endsWith("/capabilities"))
        return ok ? profile() : { detail: "Avatar runtime check failed" };
      if (options?.method === "POST")
        return { id: "unexpected", status: "queued" };
      if (path.endsWith("/hardware")) return { gpus: [] };
      return {
        id: path.endsWith("portrait") ? "portrait" : "speech",
        type: path.endsWith("portrait") ? "image" : "audio",
        mime_type: path.endsWith("portrait") ? "image/png" : "audio/wav",
        original_filename: path.endsWith("portrait")
          ? "Portrait.png"
          : "Speech.wav",
      };
    },
  }));
  vi.stubGlobal("fetch", fetch);
  const client = mount("/avatars?image=portrait&audio=speech");
  return { fetch, client };
}

it("waits for runtime readiness before enabling a fully configured form", async () => {
  let resolve!: (profile: SetupProfile) => void;
  const pending = new Promise<SetupProfile>((done) => {
    resolve = done;
  });
  const { fetch } = setupFetch(() => pending);
  await screen.findByText("Checking local avatar runtime…");
  await screen.findByText("Portrait.png");
  await screen.findByText("Speech.wav");
  const button = screen.getByRole("button", { name: "Generate avatar video" });
  expect(button.hasAttribute("disabled")).toBe(true);
  fireEvent.submit(button.closest("form")!);
  expect(fetch.mock.calls.every(([, init]) => init?.method !== "POST")).toBe(
    true,
  );
  resolve({ available: true });
  await vi.waitFor(() => expect(button.hasAttribute("disabled")).toBe(false));
});

it.each([false, true])(
  "keeps an unavailable or failed runtime form inspectable without submission (error=%s)",
  async (failed) => {
    const { fetch } = setupFetch(
      async () => ({ available: false, reason: "Echo runtime is absent" }),
      !failed,
    );
    await screen.findByText(
      failed ? "Avatar runtime check failed" : /Echo runtime is absent/,
    );
    await screen.findByText("Portrait.png");
    await screen.findByText("Speech.wav");
    const button = screen.getByRole("button", {
      name: "Generate avatar video",
    });
    expect(button.hasAttribute("disabled")).toBe(true);
    fireEvent.submit(button.closest("form")!);
    expect(fetch.mock.calls.every(([, init]) => init?.method !== "POST")).toBe(
      true,
    );
    if (!failed)
      expect(
        screen
          .getByRole("link", { name: "Inspect system" })
          .getAttribute("href"),
      ).toBe("/system");
  },
);

it("does not submit from stale available data after the runtime recheck fails", async () => {
  let failed = false;
  const { fetch, client } = setupFetch(async () => {
    if (failed) throw new Error("Avatar runtime check failed");
    return { available: true };
  });
  const button = screen.getByRole("button", { name: "Generate avatar video" });
  await vi.waitFor(() => expect(button.hasAttribute("disabled")).toBe(false));
  failed = true;
  await client.invalidateQueries({ queryKey: ["avatar-capabilities"] });
  await screen.findByText("Avatar runtime check failed");
  expect(button.hasAttribute("disabled")).toBe(true);
  fireEvent.submit(button.closest("form")!);
  expect(fetch.mock.calls.every(([, init]) => init?.method !== "POST")).toBe(
    true,
  );
});
