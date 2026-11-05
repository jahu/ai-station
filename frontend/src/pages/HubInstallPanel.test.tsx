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
import HubInstallPanel, { type InstallPlan } from "./HubInstallPanel";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const plan: InstallPlan = {
  manifest_sha256: "a".repeat(64),
  license: "apache-2.0",
  license_url: "https://huggingface.co/publisher/new-model",
  files: [
    {
      assessment: {
        hardware_status: "estimated_fit",
        disk: { status: "file_fits" },
      },
    },
  ],
};

it("lists every model part even when there are no additional engine licenses", () => {
  mount({
    ...plan,
    capability: "chat",
    components: [
      {
        role: "model part",
        filename: "model-00001-of-00002.gguf",
        size_bytes: 4 * 1024 ** 3,
      },
      {
        role: "model part",
        filename: "model-00002-of-00002.gguf",
        size_bytes: 4 * 1024 ** 3,
      },
    ],
  });
  fireEvent.click(screen.getByText("Required model files"));
  expect(screen.getByText(/model-00001-of-00002.gguf/)).toBeTruthy();
  expect(screen.getByText(/model-00002-of-00002.gguf/)).toBeTruthy();
  expect(screen.getAllByRole("checkbox")).toHaveLength(1);
});

it("requires explicit avatar workload consent and describes the correct GPU and RAM profile", async () => {
  const fetch = vi.fn(async () => ({
    ok: true,
    json: async () => ({ id: "avatar-preparation" }),
  }));
  vi.stubGlobal("fetch", fetch);
  mount({ ...plan, capability: "avatar" });
  const button = screen.getByRole("button", {
    name: "Install model",
  }) as HTMLButtonElement;
  const checks = screen.getAllByRole("checkbox");
  expect(checks).toHaveLength(2);
  fireEvent.click(checks[0]);
  expect(button.disabled).toBe(true);
  expect(
    screen.getByText(/one or two compatible GPUs of at least 12 GiB each/),
  ).toBeTruthy();
  fireEvent.click(checks[1]);
  fireEvent.click(button);
  await waitFor(() => expect(fetch).toHaveBeenCalled());
  const request = (
    fetch.mock.calls as unknown as [string, RequestInit][]
  )[0][1];
  expect(JSON.parse(String(request.body))).toEqual(
    expect.objectContaining({
      workload_accepted: true,
      license_accepted: true,
    }),
  );
});
function mount(currentPlan = plan, downloadId = "", onDownload = vi.fn()) {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <HubInstallPanel
          plan={currentPlan}
          runId="reviewed-plan"
          canManage={true}
          downloadId={downloadId}
          onDownload={onDownload}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return onDownload;
}
it("opens the installed avatar choice directly without treating it as a conversation model", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({
        id: "avatar-preparation",
        manifest_sha256: plan.manifest_sha256,
        entry: {
          name: "Installed Sonic",
          capability: "avatar",
          quantization: "F32",
          file: { size_bytes: 1024 },
        },
        definition_id: "selected-avatar",
        attempt: 1,
        run: { id: "avatar-install-run", status: "succeeded" },
        model_key: null,
        resume_allowed: false,
        progress: { ready_to_try: true },
      }),
    })),
  );
  mount({ ...plan, capability: "avatar" }, "avatar-preparation");
  const open = await screen.findByRole("link", {
    name: "Open Avatars with this model →",
  });
  expect(open.getAttribute("href")).toBe("/avatars?model=selected-avatar");
  expect(
    screen.queryByRole("button", { name: "Open Chat with this model" }),
  ).toBeNull();
});
it("requires explicit license acceptance and sends only the saved plan identity", async () => {
  const fetch = vi.fn(async (_path: string, _options?: RequestInit) => ({
    ok: _path === "/api/model-hub/downloads" && _options?.method === "POST",
    json: async () => ({ id: "preparation" }),
  }));
  vi.stubGlobal("fetch", fetch);
  const accepted = mount();
  const button = screen.getByRole("button", {
    name: "Install model",
  }) as HTMLButtonElement;
  expect(button.disabled).toBe(true);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(button);
  await waitFor(() => expect(accepted).toHaveBeenCalledWith("preparation"));
  const [path, options] = fetch.mock.calls[0];
  expect(path).toBe("/api/model-hub/downloads");
  expect(JSON.parse(String(options?.body))).toEqual({
    client_request_id: expect.any(String),
    plan_run_id: "reviewed-plan",
    manifest_sha256: plan.manifest_sha256,
    license_accepted: true,
  });
});
it("keeps installation disabled when no workload fits", () => {
  mount({
    ...plan,
    files: [
      {
        assessment: {
          hardware_status: "unknown",
          disk: { status: "file_fits" },
        },
      },
    ],
  });
  fireEvent.click(screen.getByRole("checkbox"));
  expect(
    (screen.getByRole("button", { name: "Install model" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
});
it("restores owned download progress and reuses existing Stop action without another install", async () => {
  const fetch = vi.fn(async (_path: string, _options?: RequestInit) => ({
    ok:
      _path.startsWith("/api/setup/downloads/") &&
      ["GET", "POST"].includes(_options?.method ?? "GET"),
    json: async () => ({
      id: "preparation",
      manifest_sha256: plan.manifest_sha256,
      entry: {
        name: "New model",
        file: { size_bytes: 4096, sha256: "b".repeat(64) },
        quantization: "Q4_K_M",
      },
      attempt: 1,
      run: { id: "download-run", status: "running", error_message: "" },
      model_key: null,
      resume_allowed: false,
      progress: {
        phase: "downloading",
        received_bytes: 1024,
        expected_bytes: 4096,
      },
    }),
  }));
  vi.stubGlobal("fetch", fetch);
  mount(plan, "preparation");
  await screen.findByRole("progressbar");
  fireEvent.click(screen.getByRole("button", { name: "Stop" }));
  await waitFor(() =>
    expect(
      fetch.mock.calls.some(
        ([p, o]) =>
          p === "/api/setup/downloads/preparation/cancel" &&
          o?.method === "POST",
      ),
    ).toBe(true),
  );
  expect(fetch.mock.calls.some(([p]) => p === "/api/model-hub/downloads")).toBe(
    false,
  );
});

it("reviews image component licenses and opens Images instead of creating a chat", async () => {
  const imagePlan: InstallPlan = {
    ...plan,
    capability: "image",
    components: [
      { role: "text_encoder", filename: "encoder.gguf", size_bytes: 1024 ** 3 },
    ],
    component_licenses: [
      {
        name: "Encoder Apache 2.0",
        url: "https://www.apache.org/licenses/LICENSE-2.0",
      },
    ],
  };
  const fetch = vi.fn(async () => ({
    ok: true,
    json: async () => ({
      id: "image-preparation",
      manifest_sha256: plan.manifest_sha256,
      entry: {
        name: "New image model",
        quantization: "Q4_0",
        capability: "image",
        file: { size_bytes: 1000, sha256: "b".repeat(64) },
      },
      definition_id: "new-image-definition",
      attempt: 1,
      run: { id: "download", status: "succeeded" },
      model_key: null,
      resume_allowed: false,
      progress: { ready_to_try: true },
    }),
  }));
  vi.stubGlobal("fetch", fetch);
  mount(imagePlan, "image-preparation");
  fireEvent.click(screen.getByText("Required engine, components and licenses"));
  expect(screen.getByRole("link", { name: /Encoder Apache 2.0/ })).toBeTruthy();
  const open = await screen.findByRole("link", {
    name: /Open Images with this model/,
  });
  expect(open.getAttribute("href")).toBe("/images?model=new-image-definition");
  expect(screen.queryByRole("button", { name: /Open Chat/ })).toBeNull();
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("does not install when physical memory fits but runtime prerequisites are unavailable", () => {
  mount({
    ...plan,
    capability: "image",
    files: [
      {
        assessment: {
          hardware_status: "estimated_fit",
          runtime_status: "runtime_unavailable",
          disk: { status: "file_fits" },
        },
      },
    ],
  });
  fireEvent.click(screen.getByRole("checkbox"));
  expect(
    (screen.getByRole("button", { name: "Install model" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
});

it("requires separate explicit video workload consent before installing", async () => {
  const fetch = vi.fn(async (_path: string, _options?: RequestInit) => ({
    ok: _path === "/api/model-hub/downloads" && _options?.method === "POST",
    json: async () => ({ id: "video-setup" }),
  }));
  vi.stubGlobal("fetch", fetch);
  const accepted = mount({ ...plan, capability: "video" });
  const button = screen.getByRole("button", {
    name: "Install model",
  }) as HTMLButtonElement;
  fireEvent.click(screen.getByRole("checkbox", { name: /model license/ }));
  expect(button.disabled).toBe(true);
  fireEvent.click(
    screen.getByRole("checkbox", { name: /I accept this video profile/ }),
  );
  expect(button.disabled).toBe(false);
  fireEvent.click(button);
  await waitFor(() => expect(accepted).toHaveBeenCalledWith("video-setup"));
  expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toMatchObject({
    license_accepted: true,
    workload_accepted: true,
  });
});

it("reviews speech companions with one license consent and opens the installed Audio model", async () => {
  const fetch = vi.fn(async (_path: string, _options?: RequestInit) => ({
    ok:
      _path === "/api/model-hub/downloads"
        ? _options?.method === "POST"
        : _path === "/api/setup/downloads/speech-preparation",
    json: async () => ({
      id: "speech-preparation",
      manifest_sha256: plan.manifest_sha256,
      entry: {
        name: "My speech checkpoint",
        capability: "speech",
        quantization: "F32",
        file: { size_bytes: 1000, sha256: "b".repeat(64) },
      },
      definition_id: "installed-speech",
      attempt: 1,
      run: { id: "speech-download", status: "succeeded" },
      model_key: null,
      resume_allowed: false,
      progress: { ready_to_try: true },
    }),
  }));
  vi.stubGlobal("fetch", fetch);
  const accepted = mount({
    ...plan,
    capability: "speech",
    components: [
      { role: "voice_encoder", filename: "ve.pt", size_bytes: 1024 },
    ],
    component_licenses: [{ name: "Speech MIT", url: plan.license_url }],
  });
  expect(screen.getAllByRole("checkbox")).toHaveLength(1);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Install model" }));
  await waitFor(() =>
    expect(accepted).toHaveBeenCalledWith("speech-preparation"),
  );
  expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).not.toHaveProperty(
    "workload_accepted",
  );
  cleanup();
  mount({ ...plan, capability: "speech" }, "speech-preparation");
  const open = await screen.findByRole("link", {
    name: /Open Audio with this model/,
  });
  expect(open.getAttribute("href")).toBe("/audio?model=installed-speech");
  expect(screen.queryByRole("button", { name: /Open Chat/ })).toBeNull();
});

it("disables speech installation when the complete installation does not fit disk", () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  mount({
    ...plan,
    capability: "speech",
    files: [
      {
        assessment: {
          hardware_status: "estimated_fit",
          disk: { status: "insufficient" },
        },
      },
    ],
  });
  fireEvent.click(screen.getByRole("checkbox"));
  const button = screen.getByRole("button", {
    name: "Install model",
  }) as HTMLButtonElement;
  expect(button.disabled).toBe(true);
  fireEvent.click(button);
  expect(fetch).not.toHaveBeenCalled();
});

it("requires separate consent for the music workload and its CPU offload", async () => {
  const fetch = vi.fn(async () => ({
    ok: true,
    json: async () => ({ id: "music-preparation" }),
  }));
  vi.stubGlobal("fetch", fetch);
  mount({ ...plan, capability: "music" });
  const submit = screen.getByRole("button", { name: "Install model" });
  const checks = screen.getAllByRole("checkbox");
  expect(checks).toHaveLength(2);
  fireEvent.click(checks[0]);
  expect((submit as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(checks[1]);
  expect((submit as HTMLButtonElement).disabled).toBe(false);
  fireEvent.click(submit);
  await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
  const [, options] = fetch.mock.calls[0] as unknown as [string, RequestInit];
  expect(JSON.parse(String(options.body)).workload_accepted).toBe(true);
});
