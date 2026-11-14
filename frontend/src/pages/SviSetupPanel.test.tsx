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
import { EnvironmentSetupPanel } from "./SpeechSetupPanel";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const profile = "wan22-svi-pro-q4-linux-x86-64-python312-v1";
function mount({ expanded = true, available = true, prepared = false } = {}) {
  const writes: Record<string, unknown>[] = [];
  let history: unknown[] = [];
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      writes.push(JSON.parse(String(init.body)));
      history = [
        {
          id: "setup-task",
          manifest_sha256: "a".repeat(64),
          attempt: 1,
          run: {
            id: "setup-run",
            status: "queued",
            created_at: "2026-11-14T00:00:00Z",
          },
          progress: {},
          resume_allowed: false,
        },
      ];
      return { ok: true, json: async () => history[0] };
    }
    return {
      ok: true,
      json: async () =>
        url.includes("/preparations?")
          ? history
          : {
              can_prepare: true,
              installation_available: available,
              installation_notice: available
                ? undefined
                : "SVI Pro video is still being qualified",
              manifest_sha256: "a".repeat(64),
              recipe: {
                profile,
                license_notice:
                  "Models and dependencies retain their individual licenses.",
                inputs: [
                  { filename: "high.gguf", kind: "model", size_bytes: 1024 },
                ],
              },
              managed_svi: { available: false, environment_prepared: prepared },
              recommendation: {
                fits: true,
                reason: "One 12-GiB GPU and 24 GiB system RAM.",
              },
              storage: {
                free_bytes: 100 * 1024 ** 3,
                required_bytes: 40 * 1024 ** 3,
                download_bytes: 30 * 1024 ** 3,
                cached_bytes_estimate: 0,
              },
              licenses: [
                {
                  name: "Pro adapters · MIT",
                  url: "https://example.com/license",
                },
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
          expanded ? "/setup/models?capability=svi" : "/setup/models",
        ]}
      >
        <EnvironmentSetupPanel family="svi" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { writes, fetch };
}

it("keeps optional continuous setup collapsed without contacting the Runner", async () => {
  const { fetch } = mount({ expanded: false });
  expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "Set up continuous video" }),
  );
  await screen.findByRole("button", {
    name: "Download & set up continuous video",
  });
  expect(fetch.mock.calls.every(([url]) => String(url).includes(profile))).toBe(
    true,
  );
});

it("requires both licenses and workload consent before submitting the fixed profile", async () => {
  const { writes } = mount();
  const button = await screen.findByRole("button", {
    name: "Download & set up continuous video",
  });
  expect((button as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(
    screen.getByRole("checkbox", {
      name: /I have reviewed the continuous video/,
    }),
  );
  expect((button as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(
    screen.getByRole("checkbox", { name: /I accept CPU offload/ }),
  );
  expect((button as HTMLButtonElement).disabled).toBe(false);
  fireEvent.click(button);
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0]).toMatchObject({
    profile,
    manifest_sha256: "a".repeat(64),
    license_accepted: true,
    workload_accepted: true,
  });
  expect(Object.keys(writes[0]).sort()).toEqual([
    "client_request_id",
    "license_accepted",
    "manifest_sha256",
    "profile",
    "workload_accepted",
  ]);
  await screen.findByRole("button", { name: "Stop continuous video setup" });
});

it("shows actual requirements while qualification blocks installation", async () => {
  const { writes } = mount({ available: false });
  const button = await screen.findByRole("button", {
    name: "Download & set up continuous video",
  });
  expect((button as HTMLButtonElement).disabled).toBe(true);
  expect(
    screen.getByText(/SVI Pro video is still being qualified/),
  ).toBeTruthy();
  expect(screen.getByText(/reserves 18 GiB system RAM/)).toBeTruthy();
  expect(screen.getByText(/100.00 GiB free/)).toBeTruthy();
  expect(writes).toHaveLength(0);
});

it("does not confuse prepared files with operational video readiness", async () => {
  mount({ available: false, prepared: true });
  await screen.findByRole("button", {
    name: "Download & set up continuous video",
  });
  expect(
    screen.queryByText("Your continuous video engine is ready."),
  ).toBeNull();
  expect(
    screen.queryByRole("link", { name: "Open continuous video" }),
  ).toBeNull();
});
