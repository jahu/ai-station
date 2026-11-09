import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import StationUpdates from "./StationUpdates";
import { newerVersion, type UpdateStatus } from "./station-update-contract";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function mount(overrides: Partial<UpdateStatus> = {}) {
  const data = {
    current_version: "0.4.0",
    latest_check: null,
    checked_at: null,
    release: null,
    apply_available: false,
    ...overrides,
  };
  const fetch = vi.fn<typeof window.fetch>(
    async () => new Response(JSON.stringify(data)),
  );
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <StationUpdates />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return fetch;
}

it("checks only when requested and shows the running version", async () => {
  const fetch = mount();
  await screen.findByText("v0.4.0");
  expect(fetch.mock.calls).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "Check for updates" }));
  await vi.waitFor(() => expect(fetch.mock.calls.length).toBeGreaterThan(1));
  expect(fetch.mock.calls[1][0]).toBe("/api/maintenance/updates/checks");
});

it("compares numeric versions and excludes executable release HTML", async () => {
  mount({
    current_version: "0.9.0",
    release: {
      version: "0.10.0",
      release_url: "https://github.com/jahu/ai-station/releases/tag/v0.10.0",
      notes: "<script>bad()</script>",
    },
  });
  await screen.findByText("AI Station 0.10.0 is available");
  expect(document.querySelector("script")).toBeNull();
  expect(screen.queryByText("bad()")).toBeNull();
  expect(
    screen.queryByRole("button", { name: "Update and restart" }),
  ).toBeNull();
  expect(newerVersion("0.10.0", "0.9.0")).toBe(true);
  expect(newerVersion("0.4.0", "0.4.0")).toBe(false);
  expect(newerVersion("0.3.0", "0.4.0")).toBe(false);
  expect(newerVersion("invalid", "0.4.0")).toBe(false);
});

it("keeps failed check feedback visible without claiming up to date", async () => {
  mount({
    latest_check: {
      id: "check-id",
      status: "failed",
      error_message: "The update service is busy.",
    } as UpdateStatus["latest_check"],
  });
  await screen.findByRole("alert");
  expect(screen.getByText("The update service is busy.")).toBeTruthy();
  expect(screen.queryByText("You’re up to date")).toBeNull();
  expect(
    screen
      .getByRole("link", { name: "View update check" })
      .getAttribute("href"),
  ).toBe("/runs/check-id");
});

it("starts the frozen official offer with one click and a stable request identity", async () => {
  const fingerprint = "a".repeat(64);
  const fetch = mount({
    apply_available: true,
    installation: { installed: true, platform: "linux-amd64" },
    release_check_run_id: "11111111-1111-4111-8111-111111111111",
    release: {
      version: "0.5.0",
      release_url: "https://github.com/jahu/ai-station/releases/tag/v0.5.0",
      notes: "Faster setup",
      fingerprint,
      packages: { "linux-amd64": { size_bytes: 300 * 1024 ** 2 } },
    },
  });
  fireEvent.click(
    await screen.findByRole("button", { name: "Update and restart" }),
  );
  await vi.waitFor(() =>
    expect(
      fetch.mock.calls.some(([, options]) => options?.method === "POST"),
    ).toBe(true),
  );
  const call = fetch.mock.calls.find(
    ([, options]) => options?.method === "POST",
  )!;
  expect(call[0]).toBe("/api/maintenance/updates/install");
  expect(JSON.parse(String(call[1]?.body))).toEqual({
    check_run_id: "11111111-1111-4111-8111-111111111111",
    fingerprint,
    client_request_id: expect.stringMatching(/^[a-f0-9-]{36}$/),
  });
  expect(screen.getByText(/300 MB download/)).toBeTruthy();
});

it("shows a restart in progress without offering another install or cancel", async () => {
  mount({
    update_run: {
      id: "update",
      status: "running",
      metadata: {
        update_apply_requested: true,
        native_update: { phase: "applying" },
      },
    } as UpdateStatus["update_run"],
  });
  await screen.findByText("Installing and restarting…");
  expect(
    screen.queryByRole("button", { name: "Update and restart" }),
  ).toBeNull();
  expect(screen.queryByRole("button", { name: "Cancel update" })).toBeNull();
  expect(
    screen
      .getByRole("link", { name: "View update details" })
      .getAttribute("href"),
  ).toBe("/runs/update");
});
