import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { version as buildVersion } from "../../package.json";
import StationVersion from "./StationVersion";
import { MemoryRouter } from "react-router-dom";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function show() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <StationVersion />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
it("shows the actual running API version after an update", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({ version: "0.5.1" }))),
  );
  show();
  expect(await screen.findByLabelText("AI Station version 0.5.1")).toBeTruthy();
});
it("keeps the installed build version visible while the API reconnects", () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("unavailable", { status: 503 })),
  );
  show();
  expect(
    screen.getByLabelText(`AI Station version ${buildVersion}`),
  ).toBeTruthy();
});

it("offers a subtle update link and checks an installed station without downloading", async () => {
  let queued = false;
  const fetch = vi.fn<typeof window.fetch>(async (url, options) => {
    if (String(url).endsWith("/health"))
      return new Response(JSON.stringify({ version: "0.4.0" }));
    if (options?.method === "POST") {
      expect(String(url)).toBe("/api/maintenance/updates/checks");
      queued = true;
      return new Response(JSON.stringify({ id: "check" }));
    }
    return new Response(
      JSON.stringify({
        current_version: "0.4.0",
        installation: { installed: true },
        latest_check: queued
          ? {
              id: "check",
              status: "queued",
              created_at: new Date().toISOString(),
            }
          : null,
        release: { version: "0.5.0" },
        apply_available: false,
      }),
    );
  });
  vi.stubGlobal("fetch", fetch);
  show();
  const link = await screen.findByRole("link", {
    name: "Update available: AI Station 0.5.0",
  });
  expect(link.getAttribute("href")).toBe("/settings/updates");
  await vi.waitFor(() => expect(queued).toBe(true));
  expect(
    fetch.mock.calls.filter(([, init]) => init?.method === "POST"),
  ).toHaveLength(1);
});
