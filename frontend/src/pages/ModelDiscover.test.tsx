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
import ModelDiscover from "./ModelDiscover";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function mount(path = "/models/discover") {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={[path]}>
        <ModelDiscover />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
const report = {
  repository: "publisher/image-model",
  revision: "a".repeat(40),
  observed_at: "2026-11-04T12:00:00Z",
  license: "apache-2.0",
  source_url: "https://huggingface.co/publisher/image-model",
  license_url:
    "https://huggingface.co/publisher/image-model/blob/main/README.md",
  files: [
    {
      filename: "image.gguf",
      size_bytes: 8 * 1024 ** 3,
      format: "gguf",
      sha256: null,
      unsafe_serialization: false,
      assessment: {
        reason:
          "No validated workload profile for this object yet. File size alone cannot establish VRAM fit.",
        profiles: [],
        disk: { status: "insufficient", free_bytes: 100 },
      },
    },
  ],
};
it("pastes a link, enqueues only metadata inspection and keeps unsupported GPU fit honest", async () => {
  const fetch = vi.fn(async (_path: string, options?: RequestInit) => ({
    ok: true,
    json: async () =>
      options?.method === "POST"
        ? { id: "inspection" }
        : {
            id: "inspection",
            executor_type: "model_hub_inspect",
            status: "succeeded",
            metadata: { source_inspection: report },
          },
  }));
  vi.stubGlobal("fetch", fetch);
  mount();
  fireEvent.change(screen.getByLabelText("Model name or Hugging Face link"), {
    target: { value: report.source_url },
  });
  fireEvent.click(screen.getByRole("button", { name: "Check model" }));
  await screen.findByRole("heading", { name: "image.gguf" });
  expect(screen.getByText(/No validated workload profile/)).toBeTruthy();
  expect(screen.getByText(/Not enough disk space/)).toBeTruthy();
  expect(screen.queryByRole("button", { name: /Install/ })).toBeNull();
  const call = fetch.mock.calls.find(([, opts]) => opts?.method === "POST")!;
  expect(call[0]).toBe("/api/model-hub/inspections");
  expect(JSON.parse(String(call[1]?.body)).source).toBe(report.source_url);
  expect(
    fetch.mock.calls.filter(([, opts]) => opts?.method === "POST"),
  ).toHaveLength(1);
});
it("searches names before inspecting a selected repository", async () => {
  const fetch = vi.fn(async (path: string, options?: RequestInit) => ({
    ok: true,
    json: async () => {
      if (options?.method === "POST")
        return { id: path.endsWith("searches") ? "search" : "review" };
      return {
        id: "search",
        executor_type: "model_hub_inspect",
        status: "succeeded",
        metadata: {
          source_inspection: {
            kind: "search",
            query: "new model",
            items: [
              {
                repository: "publisher/image-model",
                pipeline_hint: "text-to-image",
                downloads: 10,
              },
            ],
            files: [],
          },
        },
      };
    },
  }));
  vi.stubGlobal("fetch", fetch);
  mount();
  fireEvent.change(screen.getByLabelText("Model name or Hugging Face link"), {
    target: { value: "new model" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Search" }));
  fireEvent.click(await screen.findByRole("button", { name: "Check fit" }));
  await waitFor(() =>
    expect(
      fetch.mock.calls.filter(([, opts]) => opts?.method === "POST"),
    ).toHaveLength(2),
  );
  expect(fetch.mock.calls.some(([p]) => p === "/api/model-hub/searches")).toBe(
    true,
  );
  expect(
    fetch.mock.calls.some(([p]) => p === "/api/model-hub/inspections"),
  ).toBe(true);
});
it("restores a saved review from its Run link without submitting a new request", async () => {
  const fetch = vi.fn(async () => ({
    ok: true,
    json: async () => ({
      id: "saved",
      executor_type: "model_hub_inspect",
      status: "succeeded",
      metadata: { source_inspection: report },
    }),
  }));
  vi.stubGlobal("fetch", fetch);
  mount("/models/discover?run=saved");
  await screen.findByRole("heading", { name: "image.gguf" });
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(
    screen
      .getByRole("link", { name: "Inspection history ↗" })
      .getAttribute("href"),
  ).toBe("/runs/saved");
});
it("offers Stop while source metadata is being read", async () => {
  const fetch = vi.fn(async (_path: string, options?: RequestInit) => ({
    ok: true,
    json: async () => ({
      id: "pending",
      executor_type: "model_hub_inspect",
      status: options?.method === "POST" ? "canceled" : "running",
    }),
  }));
  vi.stubGlobal("fetch", fetch);
  mount("/models/discover?run=pending");
  fireEvent.click(await screen.findByRole("button", { name: "Stop" }));
  await waitFor(() =>
    expect(
      fetch.mock.calls.some(
        ([p, o]) => p === "/api/runs/pending/cancel" && o?.method === "POST",
      ),
    ).toBe(true),
  );
});

it("starts with a fitting variant and lets the user inspect a smaller unsupported alternative", async () => {
  const compatible = {
    ...report.files[0],
    filename: "reviewed-Q4.gguf",
    assessment: {
      ...report.files[0].assessment,
      profiles: [
        {
          catalog_id: "reviewed-profile",
          name: "Reviewed GPU model",
          fit: "estimated_fit",
          occupancy: "in_use",
          recommendation: {
            reason: "Estimated GPU fit",
            gpus: [7],
            context_size: 32768,
          },
        },
      ],
    },
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({
        id: "saved",
        executor_type: "model_hub_inspect",
        status: "succeeded",
        metadata: {
          source_inspection: {
            ...report,
            files: [report.files[0], compatible],
          },
        },
      }),
    })),
  );
  mount("/models/discover?run=saved");
  await screen.findByRole("heading", { name: "reviewed-Q4.gguf" });
  expect(screen.getByText(/32,768 context/)).toBeTruthy();
  expect(screen.getByText(/GPU memory is currently in use/)).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Choose a variant"), {
    target: { value: "image.gguf" },
  });
  expect(screen.getByRole("heading", { name: "image.gguf" })).toBeTruthy();
  expect(screen.queryByText("Reviewed GPU model")).toBeNull();
});

it("prefers the hardware recommendation and freezes an explicit longer-context target in the plan", async () => {
  const fitting = (filename: string, recommended: boolean) => ({
    ...report.files[0],
    filename,
    sha256: "b".repeat(64),
    assessment: {
      ...report.files[0].assessment,
      disk: { status: "file_fits", free_bytes: 100 * 1024 ** 3 },
      variant_advice: {
        recommended,
        context_target: 32768,
        meets_context_target: true,
        precision_tradeoff: false,
        reason: "Estimated 32,768-token context on 1 GPU(s)",
      },
      profiles: [
        {
          catalog_id: filename,
          name: filename,
          fit: "estimated_fit",
          occupancy: "in_use",
          recommendation: {
            reason: "Estimated GPU fit",
            gpus: [7],
            context_size: 32768,
          },
        },
      ],
    },
  });
  const fetch = vi.fn(async (_path: string, options?: RequestInit) => ({
    ok: true,
    json: async () =>
      options?.method === "POST"
        ? { id: "plan" }
        : {
            id: "saved",
            executor_type: "model_hub_inspect",
            status: "succeeded",
            metadata: {
              source_inspection: {
                ...report,
                observation_sha256: "a".repeat(64),
                files: [
                  fitting("large.Q8_0.gguf", false),
                  fitting("balanced.Q4_K_M.gguf", true),
                ],
              },
            },
          },
  }));
  vi.stubGlobal("fetch", fetch);
  mount("/models/discover?run=saved");
  await screen.findByRole("heading", { name: "balanced.Q4_K_M.gguf" });
  expect(screen.getByText("Recommended · gguf · 8.00 GiB")).toBeTruthy();
  fireEvent.click(screen.getByText("Context options"));
  fireEvent.change(screen.getByLabelText("Context for installation"), {
    target: { value: "131072" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Review installation" }));
  await waitFor(() =>
    expect(fetch.mock.calls.some(([p]) => p === "/api/model-hub/plans")).toBe(
      true,
    ),
  );
  const [, options] = fetch.mock.calls.find(
    ([p]) => p === "/api/model-hub/plans",
  )!;
  expect(JSON.parse(String(options?.body))).toMatchObject({
    inspection_run_id: "saved",
    filename: "balanced.Q4_K_M.gguf",
    context_target: 131072,
    observation_sha256: "a".repeat(64),
  });
});

it("explains short context and low precision instead of presenting them as a recommendation", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({
        id: "saved",
        executor_type: "model_hub_inspect",
        status: "succeeded",
        metadata: {
          source_inspection: {
            ...report,
            files: [
              {
                ...report.files[0],
                assessment: {
                  ...report.files[0].assessment,
                  variant_advice: {
                    recommended: false,
                    context_target: 32768,
                    meets_context_target: false,
                    precision_tradeoff: true,
                    reason: "Estimated 4,096-token context on 1 GPU(s)",
                  },
                  profiles: [
                    {
                      catalog_id: "limited",
                      name: "Limited GPU profile",
                      fit: "estimated_fit",
                      occupancy: "unknown",
                      recommendation: {
                        gpus: [7],
                        context_size: 4096,
                        reason: "Estimated fit",
                      },
                    },
                  ],
                },
              },
            ],
          },
        },
      }),
    })),
  );
  mount("/models/discover?run=saved");
  await screen.findByRole("heading", { name: "image.gguf" });
  expect(screen.getByText(/does not meet the 32,768-token/)).toBeTruthy();
  expect(screen.getByText(/larger precision tradeoff/)).toBeTruthy();
});
