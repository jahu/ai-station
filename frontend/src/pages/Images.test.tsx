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

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function mount(entry = "/images") {
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
}
it("queues Juggernaut parameters and keeps generation in the workspace", async () => {
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      path.endsWith("/hardware")
        ? { gpus: [{ index: 7, name: "GPU" }] }
        : { id: "run-id", status: "queued" },
  }));
  vi.stubGlobal("fetch", fetch);
  mount();
  const backendList = screen
    .getByLabelText("Backend qwen")
    .closest(".image-backend-choice-list") as HTMLElement;
  fireEvent.keyDown(backendList, { key: "End" });
  fireEvent.keyDown(backendList, { key: "Enter" });
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
it("attaches a Library image for Edit without another upload", async () => {
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
  mount();
  fireEvent.click(screen.getByLabelText("Operation img2img"));
  fireEvent.click(screen.getByRole("button", { name: "Images from Library" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Choose room.png lib-one" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Attach file" }));
  fireEvent.change(screen.getByLabelText("Edit instruction"), {
    target: { value: "Make it dusk" },
  });
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
      body: expect.stringContaining('"input_artifact_ids":["lib-one"]'),
    }),
  );
  expect(
    fetch.mock.calls.some((call) =>
      String(call[0]).includes("/images/uploads"),
    ),
  ).toBe(false);
});

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
  mount();
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
  expect(screen.getByText(/There is no inspectable source Run/)).toBeTruthy();
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
  mount("/images?mode=upscale&input=source");
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
  mount("/images?run=done");
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
