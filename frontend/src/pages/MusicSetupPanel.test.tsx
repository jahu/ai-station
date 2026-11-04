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
import MusicSetupPanel from "./MusicSetupPanel";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const profile = "ace-step15-turbo-linux-x86-64-python312-v1";
function attempt(status: string, phase = "downloading_files") {
  return {
    id: "music-task",
    manifest_sha256: "a".repeat(64),
    attempt: 1,
    run: { id: "music-run", status, created_at: "2026-10-31T00:00:00Z" },
    resume_allowed: status === "canceled",
    progress: {
      phase,
      received_bytes: 1024 ** 3,
      expected_bytes: 6 * 1024 ** 3,
      current_file: "music-weights.safetensors",
    },
  };
}
function mount({
  expanded = true,
  admin = true,
  available = true,
  ready = false,
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
                  "Model and dependencies have their own licenses.",
                inputs: [
                  { filename: "ve.pt", kind: "model", size_bytes: 1024 },
                ],
              },
              existing_music: { available: ready, source: "configured" },
              recommendation: {
                fits: available,
                reason: "One NVIDIA GPU with at least 6 GiB VRAM.",
              },
              storage: {
                free_bytes: 30 * 1024 ** 3,
                required_bytes: 14 * 1024 ** 3,
                download_bytes: 6 * 1024 ** 3,
                cached_bytes_estimate: 0,
              },
              licenses: [
                { name: "Music model", url: "https://example.com/license" },
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
          expanded ? "/setup/models?capability=music" : "/setup/models",
        ]}
      >
        <MusicSetupPanel />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { writes, fetch };
}

it("leaves optional setup collapsed without querying or downloading", async () => {
  const { fetch, writes } = mount({ expanded: false });
  expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: /Set up music/ }));
  await screen.findByRole("button", { name: /Download & set up music/ });
  expect(writes).toHaveLength(0);
});

it("shows real storage and submits only the accepted pinned receipt", async () => {
  const { writes } = mount();
  const button = await screen.findByRole("button", {
    name: /Download & set up music/,
  });
  expect((button as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText(/30.00 GiB free/)).toBeTruthy();
  fireEvent.click(
    screen.getByRole("checkbox", { name: /I have reviewed the music model/ }),
  );
  fireEvent.click(button);
  await screen.findByRole("button", { name: "Stop music setup" });
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
    await screen.findByRole("progressbar", { name: "Music files progress" }),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Stop music setup" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Resume music setup" }),
  );
  await waitFor(() => expect(writes).toHaveLength(2));
  expect(writes[1].url).toContain("/preparations/music-task/resume");
  expect(writes[1].body.expected_run_id).toBe("music-run");
});

it("keeps native installation indeterminate instead of claiming download completion is readiness", async () => {
  mount({ rows: [attempt("running", "installing_dependencies")] });
  const progress = await screen.findByRole("progressbar", {
    name: "Music engine preparation",
  });
  expect(progress.hasAttribute("value")).toBe(false);
  expect(screen.queryByText("Ready for your first recording")).toBeNull();
});

it("retains a working configured runtime without an automatic second install", async () => {
  const { writes } = mount({ ready: true });
  const link = await screen.findByRole("link", { name: /Open Music/ });
  expect(link.getAttribute("href")).toBe("/audio?mode=music");
  expect(screen.queryByRole("checkbox")).toBeNull();
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
        screen.queryByRole("button", { name: /Download & set up music/ }),
      ).toBeNull();
    } else {
      const button = await screen.findByRole("button", {
        name: /Download & set up music/,
      });
      expect((button as HTMLButtonElement).disabled).toBe(true);
    }
    expect(writes).toHaveLength(0);
  },
);
