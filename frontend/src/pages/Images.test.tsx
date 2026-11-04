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
import Images from "./Images";
import type { ImageModelCatalog } from "./image-models";

const imageCatalog: ImageModelCatalog = {
  items: [
    {
      id: "qwen",
      definition_id: null,
      name: "Qwen Image",
      backend: "qwen",
      available: true,
      modes: ["t2i", "img2img", "recompose"],
      maximum_references: 8,
    },
    {
      id: "juggernaut",
      definition_id: null,
      name: "Juggernaut XL",
      backend: "juggernaut",
      available: true,
      modes: ["t2i"],
      maximum_references: 0,
    },
    {
      id: "realesrgan",
      definition_id: null,
      name: "RealESRGAN",
      backend: "qwen",
      available: true,
      modes: ["upscale"],
      maximum_references: 1,
    },
  ],
  defaults: {
    revision: 0,
    choices: {
      t2i: "qwen",
      img2img: "qwen",
      recompose: "qwen",
      upscale: "realesrgan",
    },
  },
};

const lustifyId = "22222222-2222-4222-8222-222222222222";
function withLustify(defaultChoice = "qwen"): ImageModelCatalog {
  return {
    items: [
      ...imageCatalog.items,
      {
        id: lustifyId,
        definition_id: lustifyId,
        name: "LUSTIFY Turbo Q4",
        backend: "krea2",
        available: true,
        modes: ["t2i", "img2img", "recompose"],
        maximum_references: 2,
        gpu_count: 2,
      },
    ],
    defaults: {
      revision: 4,
      choices: { ...imageCatalog.defaults.choices, t2i: defaultChoice },
    },
  };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
async function mount(entry = "/images", catalog = imageCatalog) {
  const originalFetch = globalThis.fetch;
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
      String(input) === "/api/images/models"
        ? Promise.resolve(
            new Response(JSON.stringify(catalog), { status: 200 }),
          )
        : originalFetch(input, init),
    ),
  );
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={cache}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/images" element={<Images />} />
          <Route path="/runs/:id" element={<h1>Run inspector</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await waitFor(() =>
    expect(
      screen.getByRole("combobox", { name: "Model" }).textContent,
    ).not.toContain("Loading models…"),
  );
}
it("submits enhancement by itself with inherited translation off and no review", async () => {
  const writes: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, options?: RequestInit) => {
      if (path === "/api/images/runs" && options?.method === "POST")
        writes.push(JSON.parse(String(options.body)));
      return {
        ok: true,
        json: async () =>
          path.endsWith("/hardware")
            ? { gpus: [] }
            : path.endsWith("/generation/preferences")
              ? {
                  revision: 0,
                  enabled: false,
                  model: "local",
                  target_language: "en",
                }
              : { id: "run-id", status: "queued" },
      };
    }),
  );
  await mount();
  fireEvent.change(screen.getByLabelText("Prompt"), {
    target: { value: "A red bicycle" },
  });
  fireEvent.click(
    screen.getByRole("checkbox", { name: /Improve my prompt locally/ }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Queue generate" }));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0]).toMatchObject({
    translation: { mode: "inherit", enhance: true, review: false },
  });
});

it("queues Juggernaut parameters and keeps generation in the workspace", async () => {
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      path.endsWith("/hardware")
        ? { gpus: [{ index: 7, name: "GPU" }] }
        : { id: "run-id", status: "queued" },
  }));
  vi.stubGlobal("fetch", fetch);
  await mount();
  fireEvent.change(screen.getByRole("combobox", { name: "Model" }), {
    target: { value: "juggernaut" },
  });
  fireEvent.change(screen.getByLabelText("Prompt"), {
    target: { value: "A forest" },
  });
  fireEvent.change(screen.getByLabelText("Seed"), { target: { value: "123" } });
  await screen.findByLabelText("Target GPU 7");
  const gpuList = screen
    .getByLabelText("Target GPU auto")
    .closest(".gpu-target-choice-list") as HTMLElement;
  fireEvent.keyDown(gpuList, { key: "End" });
  fireEvent.keyDown(gpuList, { key: "Enter" });
  fireEvent.click(screen.getByRole("button", { name: "Queue generate" }));
  await screen.findByText("Waiting for an available GPU");
  expect(screen.queryByRole("heading", { name: "Run inspector" })).toBeNull();
  expect((screen.getByLabelText("Prompt") as HTMLTextAreaElement).value).toBe(
    "A forest",
  );
  expect(
    screen
      .getByRole("button", { name: "Generating…" })
      .hasAttribute("disabled"),
  ).toBe(true);
  expect(
    screen.getByRole("link", { name: "View run & logs" }).getAttribute("href"),
  ).toBe("/runs/run-id");
  expect(screen.getByRole("button", { name: "Stop generation" })).toBeTruthy();
  expect(fetch).toHaveBeenCalledWith(
    "/api/images/runs",
    expect.objectContaining({ body: expect.stringContaining('"seed":123') }),
  );
  expect(fetch).toHaveBeenCalledWith(
    "/api/images/runs",
    expect.objectContaining({ body: expect.stringContaining('"gpu":"7"') }),
  );
});
it.each([false, true])(
  "attaches a Library image for Edit with classic template=%s",
  async (classic) => {
    const artifact = {
      id: "lib-one",
      original_filename: "room.png",
      type: "image",
      mime_type: "image/png",
      metadata: { width: 200, height: 100 },
    };
    const fetch = vi.fn(async (path: string) => ({
      ok: true,
      json: async () => {
        const url = String(path);
        if (url.includes("/hardware")) return { gpus: [] };
        if (url.includes("/artifacts?")) return [artifact];
        if (url.includes("/artifacts/")) return artifact;
        return { id: "run-edit", status: "queued" };
      },
    }));
    vi.stubGlobal("fetch", fetch);
    await mount();
    fireEvent.click(screen.getByLabelText("Operation img2img"));
    fireEvent.click(
      screen.getByRole("button", { name: "Images from Library" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Choose room.png lib-one" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Attach file" }));
    fireEvent.change(screen.getByLabelText("Edit instruction"), {
      target: { value: "Make it dusk" },
    });
    const template = screen.getByRole("checkbox", {
      name: "Use classic identity template",
    }) as HTMLInputElement;
    expect(template.checked).toBe(false);
    if (classic) fireEvent.click(template);

    await waitFor(() =>
      expect(
        screen
          .getByRole("button", { name: "Queue edit" })
          .hasAttribute("disabled"),
      ).toBe(false),
    );
    fireEvent.click(screen.getByRole("button", { name: "Queue edit" }));
    await screen.findByText("Waiting for an available GPU");
    expect(screen.queryByRole("heading", { name: "Run inspector" })).toBeNull();
    expect(fetch).toHaveBeenCalledWith(
      "/api/images/runs",
      expect.objectContaining({
        body: expect.stringContaining(
          `"prompt_style":"${classic ? "pipeline" : "instruction"}"`,
        ),
      }),
    );
    expect(fetch).toHaveBeenCalledWith(
      "/api/images/runs",
      expect.objectContaining({
        body: expect.stringContaining('"input_artifact_ids":["lib-one"]'),
      }),
    );
    expect(
      fetch.mock.calls.some((call) =>
        String(call[0]).includes("/images/uploads"),
      ),
    ).toBe(false);
  },
);

it("moves through Images sources with arrow keys without queueing a Run", async () => {
  const artifacts = [
    {
      id: "lib-one",
      original_filename: "person.png",
      type: "image",
      mime_type: "image/png",
      metadata: { width: 200, height: 100 },
    },
    {
      id: "lib-two",
      original_filename: "outfit.png",
      type: "image",
      mime_type: "image/png",
      metadata: { width: 200, height: 100 },
    },
  ];
  const fetch = vi.fn(async (path: string, options?: RequestInit) => ({
    ok: options === undefined,
    json: async () => {
      const url = String(path);
      if (url.includes("/hardware")) return { gpus: [] };
      if (url.includes("/artifacts?")) return artifacts;
      if (url.includes("/artifacts/lib-two")) return artifacts[1];
      if (url.includes("/artifacts/lib-one")) return artifacts[0];
      return { id: "run-recompose" };
    },
  }));
  vi.stubGlobal("fetch", fetch);
  await mount();
  fireEvent.click(screen.getByLabelText("Operation recompose"));
  fireEvent.click(screen.getByRole("button", { name: "Images from Library" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Choose person.png lib-one" }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Choose outfit.png lib-two" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Attach 2 files" }));
  const first = await screen.findByLabelText("Source 1 lib-one");
  const second = screen.getByLabelText("Source 2 lib-two");
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(screen.getByText(/Selected references/)).toBeTruthy();
  fireEvent.keyDown(first.closest(".source-strip") as HTMLElement, {
    key: "ArrowRight",
  });
  expect(second.tabIndex).toBe(0);
  expect(document.activeElement).toBe(second);
  expect(
    screen.getByRole("button", { name: "Remove source 2 lib-two" }).tabIndex,
  ).toBe(0);
  fireEvent.keyDown(second.closest(".source-strip") as HTMLElement, {
    key: "Enter",
  });
  expect(fetch.mock.calls.every((call) => !call[1])).toBe(true);
  fireEvent.keyDown(second.closest(".source-strip") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
});

it("reuses a Library source, shows upscale dimensions, and submits its identity", async () => {
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      path.includes("/artifacts/")
        ? { id: "source", metadata: { width: 200, height: 100 } }
        : path.endsWith("/hardware")
          ? { gpus: [] }
          : { id: "next", status: "queued" },
  }));
  vi.stubGlobal("fetch", fetch);
  await mount("/images?mode=upscale&input=source");
  await screen.findByText(/Expected output: 800 × 400/);
  await waitFor(() =>
    expect(
      screen
        .getByRole("button", { name: "Queue upscale" })
        .hasAttribute("disabled"),
    ).toBe(false),
  );
  fireEvent.click(screen.getByRole("button", { name: "Queue upscale" }));
  await screen.findByText("Waiting for an available GPU");
  expect(screen.queryByRole("heading", { name: "Run inspector" })).toBeNull();
  expect(fetch).toHaveBeenCalledWith(
    "/api/images/runs",
    expect.objectContaining({
      body: expect.stringContaining('"input_artifact_ids":["source"]'),
    }),
  );
});

it("restores a completed image from the workspace URL", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => ({
      ok: true,
      json: async () =>
        path.endsWith("/lineage")
          ? {
              id: "photo",
              sources: [
                {
                  id: "source",
                  type: "image",
                  title: "Room",
                  original_filename: "room.png",
                },
              ],
              derived: [],
            }
          : path.includes("/artifacts?")
            ? [{ id: "photo", type: "image" }]
            : path.includes("/runs/")
              ? { id: "done", status: "succeeded" }
              : path.includes("/artifacts/")
                ? { id: "source", metadata: { width: 200, height: 100 } }
                : { gpus: [] },
    })),
  );
  await mount("/images?run=done");
  const image = await screen.findByAltText("Generated image");
  expect(image.getAttribute("src")).toBe("/api/artifacts/photo/file");
  expect(
    screen.getByRole("link", { name: "Open in Library" }).getAttribute("href"),
  ).toBe("/library/photo");
  expect(
    (
      await screen.findByRole("link", { name: "Inspect source Room source" })
    ).getAttribute("href"),
  ).toBe("/library/source");
  expect(screen.getByText(/There is no inspectable lineage Run/)).toBeTruthy();
});

it("retries a failed image run in the workspace without opening the inspector", async () => {
  const fetch = vi.fn(async (path: string, options?: RequestInit) => {
    const url = String(path);
    const method = options?.method ?? "GET";
    return {
      ok: true,
      json: async () => {
        if (url.endsWith("/hardware")) return { gpus: [] };
        if (method === "POST" && url.endsWith("/retry"))
          return { id: "retry-id", status: "queued" };
        if (url.includes("/runs/retry-id"))
          return { id: "retry-id", status: "queued" };
        if (url.includes("/runs/failed"))
          return {
            id: "failed",
            status: "failed",
            error_message: "GPU lost",
          };
        return { gpus: [] };
      },
    };
  });
  vi.stubGlobal("fetch", fetch);
  await mount("/images?run=failed");
  expect(await screen.findByText("Generation did not complete")).toBeTruthy();
  expect(screen.getByText("GPU lost")).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", { name: "Retry as a new run failed" }),
  );
  await screen.findByText("Waiting for an available GPU");
  expect(screen.queryByRole("heading", { name: "Run inspector" })).toBeNull();
  expect(
    screen.getByRole("link", { name: "View run & logs" }).getAttribute("href"),
  ).toBe("/runs/retry-id");
  expect(screen.getByRole("button", { name: "Stop generation" })).toBeTruthy();
  expect(fetch).toHaveBeenCalledWith(
    "/api/images/runs/failed/retry",
    expect.objectContaining({ method: "POST" }),
  );
});

it("reuses the finished image as an Edit source without queueing a Run", async () => {
  const fetch = vi.fn(async (path: string, options?: RequestInit) => ({
    ok: options === undefined,
    json: async () =>
      String(path).endsWith("/lineage")
        ? { id: "photo", sources: [], derived: [] }
        : String(path).includes("/artifacts?")
          ? [{ id: "photo", type: "image" }]
          : String(path).includes("/runs/")
            ? { id: "done", status: "succeeded" }
            : String(path).includes("/artifacts/")
              ? { id: "photo", metadata: { width: 200, height: 100 } }
              : { gpus: [] },
  }));
  vi.stubGlobal("fetch", fetch);
  await mount("/images?run=done");
  fireEvent.click(await screen.findByRole("link", { name: "Edit photo" }));
  await screen.findByRole("heading", { name: "Edit" });
  await screen.findByLabelText("Source 1 photo");
  expect(screen.getByAltText("Generated image")).toBeTruthy();
  expect(fetch.mock.calls.every((call) => !call[1])).toBe(true);
});

it("queues the optional upscale without replacing the selected image operation", async () => {
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      path.endsWith("/hardware")
        ? { gpus: [] }
        : { id: "queued", status: "queued" },
  }));
  vi.stubGlobal("fetch", fetch);
  await mount();
  fireEvent.change(screen.getByLabelText("Prompt"), {
    target: { value: "A forest" },
  });
  fireEvent.click(screen.getByLabelText(/Upscale result 4×/));
  fireEvent.click(screen.getByRole("button", { name: "Queue generate" }));
  await screen.findByText("Waiting for an available GPU");
  expect(fetch).toHaveBeenCalledWith(
    "/api/images/runs",
    expect.objectContaining({
      body: expect.stringContaining('"upscale_result":true'),
    }),
  );
  expect(fetch).toHaveBeenCalledWith(
    "/api/images/runs",
    expect.objectContaining({ body: expect.stringContaining('"mode":"t2i"') }),
  );
});

it("restores the two-step workflow and stops the active upscale instead of the completed generation", async () => {
  const first = {
    id: "base",
    capability: "image.generate",
    status: "succeeded",
    parameters: { upscale_result: true },
  };
  const second = {
    id: "enlarge",
    capability: "image.upscale",
    status: "queued",
    parameters: {},
  };
  const fetch = vi.fn(async (path: string, options?: RequestInit) => ({
    ok: true,
    json: async () => {
      if (path.endsWith("/hardware")) return { gpus: [] };
      if (path.includes("/artifacts?")) return [];
      if (path.endsWith("/workflow")) return { steps: [first, second] };
      if (path.endsWith("/cancel") && options?.method === "POST") return second;
      return first;
    },
  }));
  vi.stubGlobal("fetch", fetch);
  await mount("/images?run=base");
  await screen.findByRole("list", { name: "Image workflow" });
  expect(
    screen.getByRole("link", { name: "1. Generate" }).getAttribute("href"),
  ).toBe("/runs/base");
  expect(
    screen.getByRole("link", { name: "2. Upscale 4×" }).getAttribute("href"),
  ).toBe("/runs/enlarge");
  expect(
    screen
      .getByRole("button", { name: "Generating…" })
      .hasAttribute("disabled"),
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Stop generation" }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/runs/enlarge/cancel",
      expect.objectContaining({ method: "POST" }),
    ),
  );
  expect(
    fetch.mock.calls.some(([url]) => url === "/api/runs/base/cancel"),
  ).toBe(false);
});

it("shows the final upscaled artifact after reopening the original workflow URL", async () => {
  const first = {
    id: "base",
    capability: "image.generate",
    status: "succeeded",
    parameters: { upscale_result: true },
  };
  const second = {
    id: "enlarge",
    capability: "image.upscale",
    status: "succeeded",
    parameters: {},
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => ({
      ok: true,
      json: async () => {
        if (path.endsWith("/hardware")) return { gpus: [] };
        if (path.endsWith("/workflow")) return { steps: [first, second] };
        if (path.includes("/artifacts?run_id=enlarge"))
          return [{ id: "final", type: "image" }];
        if (path.includes("/artifacts?"))
          return [{ id: "original", type: "image" }];
        if (path.endsWith("/lineage"))
          return { id: "final", sources: [], derived: [] };
        return first;
      },
    })),
  );
  await mount("/images?run=base");
  await waitFor(() =>
    expect(screen.getByAltText("Generated image").getAttribute("src")).toBe(
      "/api/artifacts/final/file",
    ),
  );
  expect(
    screen.getByRole("link", { name: "View run & logs" }).getAttribute("href"),
  ).toBe("/runs/enlarge");
});

it("follows image-to-video after refresh and stops the active video stage", async () => {
  const original = {
    id: "source-run",
    status: "succeeded",
    capability: "image.generate",
    parameters: { video_prompt: "Mist drifts" },
  };
  const child = {
    id: "video-run",
    status: "running",
    capability: "video.generate",
    parameters: {},
  };
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      path.endsWith("/hardware")
        ? { gpus: [] }
        : path.endsWith("/workflow")
          ? { steps: [original, child] }
          : path.includes("/runs/source-run")
            ? original
            : [],
  }));
  vi.stubGlobal("fetch", fetch);
  await mount("/images?run=source-run");
  await screen.findByRole("heading", { name: "Your scene in motion" });
  expect(screen.getByRole("link", { name: /Animate scene/ })).toBeTruthy();
  fireEvent.click(
    await screen.findByRole("button", { name: "Stop generation" }),
  );
  await waitFor(() =>
    expect(
      fetch.mock.calls.some(([path]) => path === "/api/runs/video-run/cancel"),
    ).toBe(true),
  );
  expect(fetch.mock.calls.some(([path]) => path === "/api/images/runs")).toBe(
    false,
  );
});

it("uses the prompt alone by default and offers explicit portrait styling", async () => {
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      path.endsWith("/hardware")
        ? { gpus: [] }
        : { id: "run-id", status: "queued" },
  }));
  vi.stubGlobal("fetch", fetch);
  await mount();
  const style = screen.getByRole("checkbox", {
    name: "Add portrait styling",
  }) as HTMLInputElement;
  expect(style.checked).toBe(false);
  expect(
    screen.getByText(/Leave off for scenes, products and illustrations/),
  ).toBeTruthy();
  fireEvent.click(style);
  fireEvent.change(screen.getByLabelText("Prompt"), {
    target: { value: "A portrait in a forest" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Queue generate" }));
  await screen.findByText("Waiting for an available GPU");
  expect(fetch).toHaveBeenCalledWith(
    "/api/images/runs",
    expect.objectContaining({
      body: expect.stringContaining('"prompt_style":"pipeline"'),
    }),
  );
});

it("selects LUSTIFY with its own preset and freezes its model in the request", async () => {
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      path.endsWith("/hardware")
        ? { gpus: [] }
        : { id: "krea-run", status: "queued" },
  }));
  vi.stubGlobal("fetch", fetch);
  await mount("/images", withLustify());
  fireEvent.change(screen.getByLabelText("Width"), {
    target: { value: "640" },
  });
  fireEvent.change(screen.getByRole("combobox", { name: "Model" }), {
    target: { value: lustifyId },
  });
  expect((screen.getByLabelText("Steps") as HTMLInputElement).value).toBe("8");
  expect((screen.getByLabelText("CFG") as HTMLInputElement).value).toBe("1");
  expect((screen.getByLabelText("Width") as HTMLInputElement).value).toBe(
    "768",
  );
  expect(screen.queryByLabelText("Add portrait styling")).toBeNull();
  fireEvent.change(screen.getByLabelText("Prompt"), {
    target: { value: "A red bicycle" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Queue generate" }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/images/runs",
      expect.objectContaining({ body: expect.stringContaining(lustifyId) }),
    ),
  );
  const call = fetch.mock.calls.find(([url]) => url === "/api/images/runs");
  expect(
    JSON.parse((call as unknown as [string, RequestInit])[1].body as string),
  ).toMatchObject({
    backend: "krea2",
    model_id: lustifyId,
    steps: 8,
    cfg: 1,
    width: 768,
    seed: 42,
  });
});

it("restores the saved model and updates only the chosen operation default", async () => {
  const catalog = withLustify(lustifyId);
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      path.endsWith("/hardware")
        ? { gpus: [] }
        : {
            revision: 5,
            choices: { ...catalog.defaults.choices, t2i: "qwen" },
          },
  }));
  vi.stubGlobal("fetch", fetch);
  await mount("/images", catalog);
  expect(
    (screen.getByRole("combobox", { name: "Model" }) as HTMLSelectElement)
      .value,
  ).toBe(lustifyId);
  expect((screen.getByLabelText("Steps") as HTMLInputElement).value).toBe("8");
  fireEvent.change(screen.getByRole("combobox", { name: "Model" }), {
    target: { value: "qwen" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Use as default" }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/images/defaults",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ mode: "t2i", choice: "qwen", revision: 4 }),
      }),
    ),
  );
  expect(fetch.mock.calls.some(([path]) => path === "/api/images/runs")).toBe(
    false,
  );
});

it("keeps an unavailable saved model visible without silently selecting Qwen", async () => {
  const catalog = withLustify(lustifyId);
  catalog.items[catalog.items.length - 1].available = false;
  const fetch = vi.fn(async () => ({
    ok: true,
    json: async () => ({ gpus: [] }),
  }));
  vi.stubGlobal("fetch", fetch);
  await mount("/images", catalog);
  expect(
    (screen.getByRole("combobox", { name: "Model" }) as HTMLSelectElement)
      .value,
  ).toBe(lustifyId);
  expect(
    (
      screen.getByRole("button", {
        name: "Queue generate",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    screen.getByRole("option", { name: "LUSTIFY Turbo Q4 · unavailable" }),
  ).toBeTruthy();
});

it("recommends Auto for a structural edit without replacing an explicit LUSTIFY choice", async () => {
  const catalog = withLustify();
  catalog.defaults.choices.img2img = lustifyId;
  const writes: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      if (path === "/api/images/runs" && init?.method === "POST")
        writes.push(JSON.parse(String(init.body)));
      const body = init?.body ? JSON.parse(String(init.body)) : {};
      return {
        ok: true,
        json: async () =>
          path.endsWith("/recommendation")
            ? {
                policy: "structural-edit-v1",
                revision: 4,
                reason: "object_removal",
                choice: catalog.items[0],
              }
            : path.includes("/artifacts/")
              ? {
                  id: "source",
                  type: "image",
                  metadata: { width: 768, height: 1024 },
                }
              : path.endsWith("/generation/preferences")
                ? { enabled: false, model: "local" }
                : path.endsWith("/hardware")
                  ? { gpus: [] }
                  : {
                      id: "run-id",
                      status: "queued",
                      parameters: body,
                      metadata: {},
                    },
      };
    }),
  );
  await mount("/images?mode=img2img&input=source", catalog);
  fireEvent.change(screen.getByLabelText("Edit instruction"), {
    target: { value: "Remove the red book" },
  });
  await screen.findByLabelText("Structural edit recommendation");
  expect(
    (screen.getByRole("combobox", { name: "Model" }) as HTMLSelectElement)
      .value,
  ).toBe(lustifyId);
  expect(writes).toHaveLength(0);
  fireEvent.click(
    screen.getByRole("button", { name: "Use Auto for this edit" }),
  );
  await screen.findByText("Auto selects Qwen Image");
  expect(screen.queryByRole("button", { name: "Use as default" })).toBeNull();
  expect(screen.queryByLabelText("Reference strength")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Queue edit" }));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0]).toMatchObject({
    model_selection: "auto",
    model_selection_revision: 4,
    edit_prompt: "Remove the red book",
    steps: 30,
  });
  expect(writes[0]).not.toHaveProperty("backend");
  expect(writes[0]).not.toHaveProperty("model_id");
  expect(writes[0]).not.toHaveProperty("reference_strength");
  expect(writes[0]).not.toHaveProperty("seed");
});

it("uses the automatic nonstructural model's presets without submitting backend-only fields", async () => {
  const catalog = withLustify();
  catalog.defaults.choices.img2img = lustifyId;
  const writes: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      if (path === "/api/images/runs" && init?.method === "POST")
        writes.push(JSON.parse(String(init.body)));
      return {
        ok: true,
        json: async () =>
          path.endsWith("/recommendation")
            ? {
                policy: "structural-edit-v1",
                revision: 4,
                reason: "station_default",
                choice: catalog.items.at(-1),
              }
            : path.includes("/artifacts/")
              ? {
                  id: "source",
                  type: "image",
                  metadata: { width: 768, height: 1024 },
                }
              : path.endsWith("/hardware")
                ? { gpus: [] }
                : {
                    id: "run-id",
                    status: "queued",
                    parameters: {},
                    metadata: {},
                  },
      };
    }),
  );
  await mount("/images?mode=img2img&input=source&model=auto", catalog);
  fireEvent.change(screen.getByLabelText("Edit instruction"), {
    target: { value: "Make the lighting warmer" },
  });
  await screen.findByText("Auto selects LUSTIFY Turbo Q4");
  fireEvent.click(screen.getByRole("button", { name: "Queue edit" }));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0]).toMatchObject({
    model_selection: "auto",
    model_selection_revision: 4,
    steps: 8,
    max_side: 1024,
    prompt_style: "instruction",
  });
  for (const field of [
    "backend",
    "model_id",
    "seed",
    "negative",
    "reference_strength",
    "reference_layout",
  ])
    expect(writes[0]).not.toHaveProperty(field);
});

it("opens guided setup for an unavailable photo engine without submitting a failed generation", async () => {
  const writes: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, options?: RequestInit) => {
      if (options?.method === "POST") writes.push(path);
      return {
        ok: true,
        json: async () =>
          path === "/api/images/capabilities"
            ? { available: false, status: "unavailable" }
            : path.endsWith("/hardware")
              ? { gpus: [] }
              : path.endsWith("/generation/preferences")
                ? { enabled: false, revision: 0 }
                : [],
      };
    }),
  );
  await mount();
  const link = await screen.findByRole("link", { name: "Set up images" });
  expect(link.getAttribute("href")).toBe("/setup/models?capability=images");
  fireEvent.change(screen.getByLabelText("Prompt"), {
    target: { value: "A forest" },
  });
  expect(
    (
      screen.getByRole("button", {
        name: "Queue generate",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(writes).toHaveLength(0);
});
