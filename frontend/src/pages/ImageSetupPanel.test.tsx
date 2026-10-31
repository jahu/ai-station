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
import ImageSetupPanel from "./ImageSetupPanel";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const profile = "qwen-image21-cuda-linux-amd64-v1";
const manifest = "a".repeat(64);
function attempt(status: string, phase = "downloading_files", hash = manifest) {
  return {
    id: "image-task",
    manifest_sha256: hash,
    attempt: 1,
    run: { id: "image-run", status, created_at: "2026-10-31T00:00:00Z" },
    resume_allowed: status === "canceled",
    progress: {
      phase,
      received_bytes: 1024 ** 3,
      expected_bytes: 12 * 1024 ** 3,
      current_file: "diffusion.gguf",
    },
  };
}
function mount({
  expanded = true,
  admin = true,
  available = true,
  ready = false,
  rows = [] as ReturnType<typeof attempt>[],
  free = 40,
  configured = false,
} = {}) {
  const writes: { url: string; body: Record<string, unknown> }[] = [];
  let history = rows;
  let hash = manifest;
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      writes.push({ url, body: JSON.parse(String(init.body)) });
      history = [attempt(url.endsWith("/cancel") ? "canceled" : "queued")];
      return { ok: true, json: async () => history[0] };
    }
    return {
      ok: true,
      json: async () =>
        url.includes("/preparations?")
          ? history
          : {
              can_prepare: admin,
              installation_available: available,
              installation_notice: available
                ? undefined
                : "This profile is still being qualified",
              manifest_sha256: hash,
              recipe: {
                name: "Qwen Image 2.1 · Q4_K_M",
                inputs: [
                  "diffusion",
                  "text_encoder",
                  "vision_projector",
                  "vae",
                  "upscaler",
                ].map((role, index) => ({
                  role,
                  filename: role + ".gguf",
                  size_bytes: 1024 ** 3,
                  sha256: String(index).repeat(64),
                  url: `https://models.example.com/${role}`,
                })),
              },
              existing_images: {
                available: ready,
                source: configured ? "configured" : "managed",
              },
              hardware: {
                gpus: [
                  {
                    index: 7,
                    name: "NVIDIA test GPU",
                    memory_total_mib: 12288,
                  },
                ],
              },
              storage: {
                free_bytes: free * 1024 ** 3,
                required_bytes: 14 * 1024 ** 3,
                download_bytes: 14 * 1024 ** 3,
                cached_model_bytes_estimate: 2 * 1024 ** 3,
                docker_required_bytes: 12 * 1024 ** 3,
                docker_free_bytes: 35 * 1024 ** 3,
              },
              licenses: [
                {
                  name: "Qwen Research License",
                  url: "https://models.example.com/qwen-license",
                },
                {
                  name: "RealESRGAN · BSD 3-Clause",
                  url: "https://models.example.com/upscaler-license",
                },
              ],
            },
    };
  });
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider client={cache}>
      <MemoryRouter
        initialEntries={[
          expanded ? "/setup/models?capability=images" : "/setup/models",
        ]}
      >
        <ImageSetupPanel />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return {
    writes,
    fetch,
    changeSource: () => {
      hash = "b".repeat(64);
      void cache.invalidateQueries({ queryKey: ["image-setup-catalog"] });
    },
  };
}

it("opens image setup on demand without making a background installation", async () => {
  const { writes, fetch } = mount({ expanded: false });
  expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: /Set up images/ }));
  await screen.findByRole("button", { name: /Download & set up images/ });
  expect(writes).toHaveLength(0);
});

it("shows complete model sources, separate licenses and both storage budgets before consent", async () => {
  const { writes } = mount();
  const button = await screen.findByRole("button", {
    name: /Download & set up images/,
  });
  expect((button as HTMLButtonElement).disabled).toBe(true);
  expect(
    screen.getByText(/40.00 GiB free in application storage/),
  ).toBeTruthy();
  expect(
    screen
      .getByRole("link", { name: "Qwen Research License" })
      .getAttribute("href"),
  ).toContain("qwen-license");
  expect(screen.getByRole("link", { name: /BSD 3-Clause/ })).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "upscaler.gguf" }).getAttribute("href"),
  ).toBe("https://models.example.com/upscaler");
  fireEvent.click(
    screen.getByRole("checkbox", { name: /I have reviewed the image model/ }),
  );
  fireEvent.click(button);
  await screen.findByRole("button", { name: "Stop image setup" });
  expect(writes).toHaveLength(1);
  expect(writes[0].body).toEqual({
    client_request_id: expect.any(String),
    profile,
    manifest_sha256: manifest,
    license_accepted: true,
  });
});

it("restores saved download progress and resumes the same task after Stop", async () => {
  const { writes } = mount({ rows: [attempt("running")] });
  const progress = await screen.findByRole("progressbar", {
    name: "Image setup download progress",
  });
  expect(progress.getAttribute("value")).toBe(String(1024 ** 3));
  fireEvent.click(screen.getByRole("button", { name: "Stop image setup" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Resume image setup" }),
  );
  await waitFor(() => expect(writes).toHaveLength(2));
  expect(writes[1].url).toContain("/preparations/image-task/resume");
  expect(writes[1].body.expected_run_id).toBe("image-run");
});

it("keeps engine checks indeterminate and never presents them as a finished image", async () => {
  mount({ rows: [attempt("running", "runtime_verifying")] });
  const progress = await screen.findByRole("progressbar", {
    name: "Image engine preparation",
  });
  expect(progress.hasAttribute("value")).toBe(false);
  expect(screen.queryByRole("link", { name: "Create an image" })).toBeNull();
});

it("preserves a working configured image integration without another automatic download", async () => {
  const { writes } = mount({ ready: true, configured: true });
  const link = await screen.findByRole("link", { name: /Open Images/ });
  expect(link.getAttribute("href")).toBe("/images");
  expect(screen.queryByRole("checkbox")).toBeNull();
  expect(writes).toHaveLength(0);
});

it("can verify and register an already prepared local bundle without a duplicate download", async () => {
  const { writes } = mount({ ready: true });
  fireEvent.click(
    await screen.findByRole("button", { name: "Review installation" }),
  );
  fireEvent.click(
    screen.getByRole("checkbox", { name: /I have reviewed the image model/ }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Verify image installation" }),
  );
  await screen.findByRole("button", { name: "Stop image setup" });
  expect(writes).toHaveLength(1);
  expect(writes[0].body.profile).toBe(profile);
});

it.each([{ admin: false }, { available: false }, { free: 1 }])(
  "prevents unauthorized or unavailable preparation: %j",
  async (options) => {
    const { writes } = mount(options);
    if (options.admin === false) {
      await screen.findByText(/Your administrator can install/);
      expect(
        screen.queryByRole("button", { name: /Download & set up images/ }),
      ).toBeNull();
    } else {
      const button = await screen.findByRole("button", {
        name: /Download & set up images/,
      });
      expect((button as HTMLButtonElement).disabled).toBe(true);
    }
    expect(writes).toHaveLength(0);
  },
);

it("requires fresh consent after the source fingerprint changes", async () => {
  const { changeSource, writes } = mount();
  const checkbox = await screen.findByRole("checkbox", {
    name: /I have reviewed the image model/,
  });
  fireEvent.click(checkbox);
  changeSource();
  await waitFor(() =>
    expect((checkbox as HTMLInputElement).checked).toBe(false),
  );
  expect(
    (
      screen.getByRole("button", {
        name: /Download & set up images/,
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(writes).toHaveLength(0);
});

it("allows a new reviewed setup instead of trapping the user in an obsolete canceled recipe", async () => {
  mount({ rows: [attempt("canceled", "downloading_files", "b".repeat(64))] });
  await screen.findByText(/earlier model bundle/);
  expect(
    (
      screen.getByRole("button", {
        name: "Resume image setup",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    screen.getByRole("button", { name: /Download & set up images/ }),
  ).toBeTruthy();
});

it("requires current runtime readiness before offering the first image action", async () => {
  mount({
    available: false,
    ready: false,
    rows: [attempt("succeeded", "image_environment_prepared")],
  });
  await screen.findByText("Installation prepared");
  expect(screen.queryByRole("link", { name: "Create an image" })).toBeNull();
});
