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
import MemorySetupPanel from "./MemorySetupPanel";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const run = (status = "running") => ({
  id: "private-memory-run",
  capability: "memory.embed.prepare",
  status,
  metadata: {
    embedding_download: {
      file: "weights.onnx",
      received_bytes: 5,
      expected_bytes: 10,
    },
  },
});
function mount({
  expanded = true,
  ready = false,
  external = false,
  admin = true,
  installed = false,
  available = true,
  free = 1000,
  current = null as ReturnType<typeof run> | null,
} = {}) {
  const writes: { url: string; body: Record<string, unknown> }[] = [];
  let preparation = current;
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      writes.push({
        url,
        body: init.body ? JSON.parse(String(init.body)) : {},
      });
      preparation = run(url.endsWith("/cancel") ? "canceled" : "queued");
      return { ok: true, json: async () => preparation };
    }
    return {
      ok: true,
      json: async () => ({
        can_prepare: admin,
        configured: ready,
        backend: external ? "endpoint" : "local_cpu",
        model: external ? "my-existing-model" : "e5",
        revision: 7,
        prepare_run: preparation,
        local_model: {
          id: "pinned-e5",
          name: "Multilingual E5 Small",
          revision: "fixed-revision",
          license: "MIT",
          source_url: "https://huggingface.co/example/tree/fixed-revision",
          size_bytes: 100 * 1024 ** 2,
          available,
          installed: installed || (ready && !external),
          storage: {
            free_bytes: free * 1024 ** 2,
            required_bytes: 164 * 1024 ** 2,
            cached_bytes_estimate: installed ? 100 * 1024 ** 2 : 0,
          },
          files: [
            {
              filename: "weights.onnx",
              url: "https://huggingface.co/example/resolve/fixed-revision/weights.onnx",
              size_bytes: 100 * 1024 ** 2,
              sha256: "a".repeat(64),
            },
          ],
        },
      }),
    };
  });
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
          },
        })
      }
    >
      <MemoryRouter
        initialEntries={[
          expanded ? "/setup/models?capability=memory" : "/setup/models",
        ]}
      >
        <MemorySetupPanel />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { fetch, writes };
}

it("keeps the setup card quiet until opened", () => {
  const { fetch } = mount({ expanded: false });
  expect(screen.getByRole("button", { name: /Set up memory/ })).toBeTruthy();
  expect(fetch).not.toHaveBeenCalled();
});
it("reviews sources and requires explicit consent before using existing preparation API", async () => {
  const { writes } = mount();
  const button = await screen.findByRole("button", {
    name: "Download & set up memory",
  });
  expect((button as HTMLButtonElement).disabled).toBe(true);
  expect(
    screen
      .getByRole("link", { name: /Multilingual E5 Small · MIT license/ })
      .getAttribute("href"),
  ).toContain("fixed-revision");
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(button);
  await waitFor(() =>
    expect(writes).toEqual([
      {
        url: "/api/memory/embeddings/prepare",
        body: {
          model_id: "pinned-e5",
          expected_revision: 7,
          confirm_download: true,
        },
      },
    ]),
  );
});
it("reuses verified installed models without asking for another download", async () => {
  const { writes } = mount({ installed: true });
  fireEvent.click(
    await screen.findByRole("button", { name: "Use local memory model" }),
  );
  await waitFor(() => expect(writes[0]?.body.confirm_download).toBe(false));
});
it("preserves an existing endpoint unless the user explicitly opens replacement", async () => {
  const { writes } = mount({ ready: true, external: true });
  await screen.findByRole("link", { name: /Open Memory/ });
  expect(
    screen.queryByRole("button", { name: "Download & set up memory" }),
  ).toBeNull();
  expect(writes).toEqual([]);
  fireEvent.click(
    screen.getByRole("button", { name: "Use a local CPU model instead" }),
  );
  expect(
    screen.getByText(/explicitly replaces the configured embedding endpoint/),
  ).toBeTruthy();
  expect(
    (
      screen.getByRole("button", {
        name: "Download & set up memory",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
});
it("shows shared readiness but no install controls to an ordinary member", async () => {
  mount({ admin: false });
  await screen.findByText(/Your administrator can install/);
  expect(
    screen.queryByRole("button", { name: "Download & set up memory" }),
  ).toBeNull();
  expect(screen.queryByRole("checkbox")).toBeNull();
});
it("restores measured download activity and Stops only the saved Run", async () => {
  const { writes } = mount({ current: run() });
  const progress = await screen.findByRole("progressbar", {
    name: "Memory model download progress",
  });
  expect(progress.getAttribute("value")).toBe("5");
  fireEvent.click(screen.getByRole("button", { name: "Stop memory setup" }));
  await waitFor(() =>
    expect(writes[0]?.url).toBe("/api/runs/private-memory-run/cancel"),
  );
});
it("blocks unavailable CPU engines and insufficient storage", async () => {
  mount({ available: false, free: 10 });
  await screen.findByText(/does not include the CPU embedding engine/);
  expect(screen.getByText(/More free application storage/)).toBeTruthy();
  expect(
    (
      screen.getByRole("button", {
        name: "Download & set up memory",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
});
it("keeps a stopped preparation visible without calling a retry byte-range Resume", async () => {
  mount({ current: run("canceled"), installed: true });
  await screen.findByText(/An unfinished file is downloaded again/);
  expect(
    screen.getByRole("link", { name: "View details" }).getAttribute("href"),
  ).toBe("/runs/private-memory-run");
  expect(
    screen.getByRole("button", { name: "Use local memory model" }),
  ).toBeTruthy();
});

it("does not label a configured endpoint as tested runtime readiness", async () => {
  mount({ ready: true, external: true });
  await screen.findByText("Endpoint configured");
  expect(screen.queryByText("Ready", { exact: true })).toBeNull();
});
it("cannot mark installed local files Ready when the CPU engine is unavailable", async () => {
  mount({ ready: true, available: false });
  await screen.findByText(/does not include the CPU embedding engine/);
  expect(screen.queryByText("Ready", { exact: true })).toBeNull();
});
