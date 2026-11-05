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

it("compares a saved search and reviews its immutable variants without another inspection", async () => {
  const search = {
    kind: "search",
    query: "small models",
    observation_sha256: "a".repeat(64),
    files: [],
    items: [
      {
        repository: report.repository,
        pipeline_hint: "text-generation",
        downloads: 10,
      },
    ],
  };
  const nested = {
    ...report,
    observation_sha256: "b".repeat(64),
    files: [{ ...report.files[0], sha256: "c".repeat(64) }],
  };
  const comparison = {
    kind: "comparison",
    search_run_id: "search",
    context_target: 131072,
    files: [],
    observed_at: report.observed_at,
    items: [
      {
        repository: report.repository,
        suitability: "unsupported",
        summary: "Needs its own runtime profile",
        observation: nested,
      },
    ],
  };
  const fetch = vi.fn(async (path: string, options?: RequestInit) => ({
    ok: true,
    json: async () =>
      options?.method === "POST"
        ? { id: "comparison" }
        : {
            id: path.endsWith("/search") ? "search" : "comparison",
            executor_type: "model_hub_inspect",
            status: "succeeded",
            metadata: {
              source_inspection: path.endsWith("/search") ? search : comparison,
            },
          },
  }));
  vi.stubGlobal("fetch", fetch);
  mount("/models/discover?run=search");
  await screen.findByRole("button", { name: "Compare top 3 for my hardware" });
  fireEvent.change(screen.getByLabelText("Conversation context target"), {
    target: { value: "131072" },
  });
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Compare top 3 for my hardware",
    }),
  );
  await screen.findByRole("heading", { name: "Models for your station" });
  expect(screen.getByText("Needs a compatible runtime")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /Review variants/ }));
  await screen.findByRole("heading", { name: "image.gguf" });
  expect(
    (screen.getByLabelText("Context for installation") as HTMLSelectElement)
      .value,
  ).toBe("131072");
  fireEvent.click(
    screen.getByRole("button", { name: /Back to compared models/ }),
  );
  await screen.findByRole("heading", { name: "Models for your station" });
  const posts = fetch.mock.calls.filter(
    ([, options]) => options?.method === "POST",
  );
  expect(posts).toHaveLength(1);
  expect(posts[0][0]).toBe("/api/model-hub/comparisons");
  expect(JSON.parse(String(posts[0][1]?.body))).toMatchObject({
    search_run_id: "search",
    observation_sha256: search.observation_sha256,
    context_target: 131072,
  });
  expect(fetch.mock.calls.some(([path]) => path.endsWith("/inspections"))).toBe(
    false,
  );
});

it("keeps an inaccessible comparison source visible with a separate inspection action", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({
        id: "comparison",
        executor_type: "model_hub_inspect",
        status: "succeeded",
        metadata: {
          source_inspection: {
            kind: "comparison",
            files: [],
            items: [
              {
                repository: "publisher/gated",
                suitability: "unavailable",
                summary: "Publisher access required",
              },
            ],
          },
        },
      }),
    })),
  );
  mount("/models/discover?run=comparison");
  await screen.findByText("Source unavailable");
  expect(screen.getByText("Publisher access required")).toBeTruthy();
  expect(screen.queryByRole("button", { name: /Review variants/ })).toBeNull();
  expect(
    screen.getByRole("button", { name: /Inspect separately/ }),
  ).toBeTruthy();
});
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

it.each([true, false])(
  "reviews a whole split model without offering a fragment installation, complete=%s",
  async (complete) => {
    const identity = "b".repeat(64);
    const names = [1, 2].map((i) => `Q4/Coder.Q4_K_M-0000${i}-of-00002.gguf`);
    const assessment = {
      reason: "This split model needs a complete compatible bundle plan.",
      hardware_status: "unknown",
      runtime_status: "needs_complete_bundle_runtime",
      profiles: [],
      disk: {
        status: complete ? "insufficient" : "unknown",
        free_bytes: 10 * 1024 ** 3,
        model_bundle_bytes: complete ? 16 * 1024 ** 3 : null,
      },
    };
    const state = {
      ...report,
      observation_sha256: "a".repeat(64),
      model_bundles: [
        {
          id: identity,
          kind: "gguf_split",
          name: "Q4/Coder.Q4_K_M.gguf",
          expected_parts: 2,
          observed_parts: complete ? 2 : 1,
          status: complete ? "complete_metadata" : "missing_parts",
          total_size_bytes: complete ? 16 * 1024 ** 3 : null,
          missing_parts: complete ? [] : [2],
          parts: names.slice(0, complete ? 2 : 1).map((filename, index) => ({
            filename,
            index: index + 1,
            size_bytes: 8 * 1024 ** 3,
          })),
        },
      ],
      files: names.slice(0, complete ? 2 : 1).map((filename) => ({
        ...report.files[0],
        filename,
        bundle_id: identity,
        sha256: "c".repeat(64),
        assessment,
      })),
    };
    const fetch = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        id: "saved",
        executor_type: "model_hub_inspect",
        status: "succeeded",
        metadata: { source_inspection: state },
      }),
    }));
    vi.stubGlobal("fetch", fetch);
    mount("/models/discover?run=saved");
    await screen.findByRole("heading", { name: "Coder.Q4_K_M.gguf" });
    expect(
      screen.queryByRole("button", { name: "Review installation" }),
    ).toBeNull();
    expect(screen.queryByLabelText("Choose a variant")).toBeNull();
    fireEvent.click(
      screen.getByText(`Required model files (${complete ? 2 : 1}/2)`),
    );
    expect(
      screen.getByText(new RegExp(names[0].replaceAll(".", "\\."))),
    ).toBeTruthy();
    if (complete) {
      expect(screen.getByText(/Model weights total 16\.00 GiB/)).toBeTruthy();
      expect(screen.getByText(/Not enough disk space/)).toBeTruthy();
    } else {
      expect(screen.getByText(/Missing parts: 2/)).toBeTruthy();
      expect(screen.getByText(/Complete model size is unknown/)).toBeTruthy();
    }
    expect(
      fetch.mock.calls.every(
        (args) => !(args as unknown as [string, RequestInit?])[1]?.method,
      ),
    ).toBe(true);
  },
);

it("keeps older split-file observations unavailable without confusing unknown total size with free disk", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({
        id: "legacy",
        executor_type: "model_hub_inspect",
        status: "succeeded",
        metadata: {
          source_inspection: {
            ...report,
            observation_sha256: "a".repeat(64),
            files: [
              {
                ...report.files[0],
                filename: "Old-00001-of-00002.gguf",
                sha256: "b".repeat(64),
                assessment: {
                  ...report.files[0].assessment,
                  disk: { status: "unknown", free_bytes: 1000 * 1024 ** 3 },
                  variant_advice: {
                    recommended: true,
                    reason: "Old cached recommendation",
                  },
                  profiles: [
                    {
                      catalog_id: "old",
                      name: "Old single-file fit",
                      fit: "estimated_fit",
                      occupancy: "unknown",
                      recommendation: {
                        gpus: [7],
                        context_size: 32768,
                        reason: "Old cached fit",
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
  mount("/models/discover?run=legacy");
  await screen.findByText(/Complete model size is unknown/);
  expect(screen.queryByText("Old single-file fit")).toBeNull();
  expect(screen.queryByText(/^Recommended ·/)).toBeNull();
  expect(
    screen.queryByRole("button", { name: "Review installation" }),
  ).toBeNull();
});
