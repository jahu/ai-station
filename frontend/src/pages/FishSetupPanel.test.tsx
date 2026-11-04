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
import FishSetupPanel from "./FishSetupPanel";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const profile = "fish-s2-pro-linux-x86-64-python312-v1";
function attempt(status: string, phase = "downloading_files") {
  return {
    id: "fish-task",
    manifest_sha256: "a".repeat(64),
    attempt: 1,
    run: { id: "fish-run", status, created_at: "2026-10-31T00:00:00Z" },
    resume_allowed: status === "canceled",
    progress: {
      phase,
      received_bytes: 1024 ** 3,
      expected_bytes: 6 * 1024 ** 3,
      current_file: "fish-weights.safetensors",
    },
  };
}
function mount({
  expanded = true,
  admin = true,
  available = true,
  ready = false,
  checking = false,
  rows = [] as ReturnType<typeof attempt>[],
} = {}) {
  const writes: { url: string; body: Record<string, unknown> }[] = [];
  let history = rows;
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
                : "Requires a compatible NVIDIA GPU",
              manifest_sha256: "a".repeat(64),
              recipe: {
                profile,
                license_notice:
                  "Fish Audio terms apply. Other components retain their own terms.",
                inputs: [
                  { filename: "ve.pt", kind: "model", size_bytes: 1024 },
                ],
              },
              existing_fish: {
                available: ready,
                source: "configured",
                readiness: checking ? "checking" : undefined,
              },
              recommendation: {
                fits: available,
                reason:
                  "Two compatible GPUs with 10 + 5 GiB VRAM and 24 GiB available RAM.",
              },
              storage: {
                free_bytes: 30 * 1024 ** 3,
                required_bytes: 14 * 1024 ** 3,
                download_bytes: 6 * 1024 ** 3,
                cached_bytes_estimate: 0,
              },
              licenses: [
                { name: "Avatar model", url: "https://example.com/license" },
              ],
            },
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
          expanded ? "/setup/models?capability=fish" : "/setup/models",
        ]}
      >
        <FishSetupPanel />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { writes, fetch };
}

it("leaves optional setup collapsed without querying or downloading", async () => {
  const { fetch, writes } = mount({ expanded: false });
  expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: /Set up expressive voice/ }),
  );
  await screen.findByRole("button", {
    name: /Download & set up expressive voice/,
  });
  expect(writes).toHaveLength(0);
});

it("shows real storage and submits only the accepted pinned receipt", async () => {
  const { writes } = mount();
  const button = await screen.findByRole("button", {
    name: /Download & set up expressive voice/,
  });
  expect((button as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText(/30.00 GiB free/)).toBeTruthy();
  fireEvent.click(
    screen.getByRole("checkbox", {
      name: /I have reviewed the expressive voice model/,
    }),
  );
  fireEvent.click(button);
  await screen.findByRole("button", { name: "Stop expressive voice setup" });
  expect(writes).toHaveLength(1);
  expect(Object.keys(writes[0].body).sort()).toEqual([
    "client_request_id",
    "license_accepted",
    "manifest_sha256",
    "profile",
  ]);
  expect(writes[0].body).toMatchObject({
    profile,
    manifest_sha256: "a".repeat(64),
    license_accepted: true,
  });
});

it("restores progress and resumes the same task after Stop", async () => {
  const { writes } = mount({ rows: [attempt("running")] });
  expect(
    await screen.findByRole("progressbar", {
      name: "Expressive voice files progress",
    }),
  ).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", { name: "Stop expressive voice setup" }),
  );
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Resume expressive voice setup",
    }),
  );
  await waitFor(() => expect(writes).toHaveLength(2));
  expect(writes[1].url).toContain("/preparations/fish-task/resume");
  expect(writes[1].body.expected_run_id).toBe("fish-run");
});

it("keeps native installation indeterminate instead of claiming download completion is readiness", async () => {
  mount({ rows: [attempt("running", "installing_dependencies")] });
  const progress = await screen.findByRole("progressbar", {
    name: "Expressive voice engine preparation",
  });
  expect(progress.hasAttribute("value")).toBe(false);
  expect(screen.queryByText("Ready for your first recording")).toBeNull();
});

it("retains a working configured runtime without an automatic second install", async () => {
  const { writes } = mount({ ready: true });
  const link = await screen.findByRole("link", {
    name: /Open expressive speech/,
  });
  expect(link.getAttribute("href")).toBe("/audio?engine=fish_s2_pro");
  expect(screen.queryByRole("checkbox")).toBeNull();
  expect(writes).toHaveLength(0);
});

it("waits for checked existing weights without offering a second installation", async () => {
  const { writes } = mount({ checking: true });
  await screen.findByText(/Checking the installed expressive voice files/);
  expect(
    screen.queryByRole("button", {
      name: /Download & set up expressive voice/,
    }),
  ).toBeNull();
  expect(writes).toHaveLength(0);
});

it.each([
  { admin: false, available: true },
  { admin: true, available: false },
])(
  "prevents incompatible or unprivileged setup: %j",
  async ({ admin, available }) => {
    const { writes } = mount({ admin, available });
    if (!admin) {
      expect(
        await screen.findByText(/Your administrator can install/),
      ).toBeTruthy();
      expect(
        screen.queryByRole("button", {
          name: /Download & set up expressive voice/,
        }),
      ).toBeNull();
    } else {
      const button = await screen.findByRole("button", {
        name: /Download & set up expressive voice/,
      });
      expect((button as HTMLButtonElement).disabled).toBe(true);
    }
    expect(writes).toHaveLength(0);
  },
);
