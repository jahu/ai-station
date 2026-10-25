import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import TailnetAccess from "./TailnetAccess";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const origin = "https://ai-station.tail123.ts.net";
const base = {
  available: true,
  installed: true,
  revision: 3,
  enabled: false,
  serving: false,
  state: "stopped",
};
function mount(value: Record<string, unknown> = base, configured = true) {
  const fetch = vi.fn(async (path: string, options?: RequestInit) => {
    if (options?.method === "POST")
      return {
        ok: true,
        json: async () => ({ id: "new-run", status: "queued" }),
      };
    if (path.endsWith("/link"))
      return {
        ok: true,
        json: async () => ({
          url: "https://login.tailscale.com/a/PRIVATE-LINK",
        }),
      };
    return { ok: true, json: async () => value };
  });
  vi.stubGlobal("fetch", fetch);
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={cache}>
      <TailnetAccess configured={configured} />
    </QueryClientProvider>,
  );
  return { fetch, cache };
}

it("requires the existing password without starting or inspecting a service", () => {
  const { fetch } = mount(base, false);
  expect(screen.getByText("Set a password first")).toBeTruthy();
  expect(fetch).not.toHaveBeenCalled();
});

it("offers explicit verified installation with a visible download size", async () => {
  const { fetch } = mount({
    ...base,
    installed: false,
    state: "not_installed",
  });
  fireEvent.click(
    await screen.findByRole("button", { name: "Install private access" }),
  );
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/private-access",
      expect.objectContaining({ method: "POST" }),
    ),
  );
  const request = fetch.mock.calls.find(([, o]) => o?.method === "POST");
  expect(JSON.parse(String(request![1]!.body))).toMatchObject({
    operation: "install",
    expected_revision: 3,
  });
  expect(screen.getByText(/about 40 MB/)).toBeTruthy();
});

it("queues a start instead of asking the user for commands", async () => {
  const { fetch } = mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Start private connection" }),
  );
  await waitFor(() =>
    expect(
      fetch.mock.calls.some(
        ([, o]) => o?.body && JSON.parse(String(o.body)).operation === "start",
      ),
    ).toBe(true),
  );
});

it("sends the actual node and HTTPS origin when enabling", async () => {
  const value = {
    ...base,
    state: "Running",
    node_online: true,
    node_id: "node123",
    origin,
  };
  const { fetch } = mount(value);
  fireEvent.click(
    await screen.findByRole("button", { name: "Enable private access" }),
  );
  await waitFor(() => {
    const request = fetch.mock.calls.find(([, o]) => o?.method === "POST");
    expect(JSON.parse(String(request![1]!.body))).toMatchObject({
      operation: "enable",
      node_id: "node123",
      origin,
    });
  });
});

it("loads an interactive sign-in link only on request", async () => {
  const value = {
    ...base,
    state: "NeedsLogin",
    run: {
      id: "login-run",
      status: "succeeded",
      parameters: { operation: "login" },
      metadata: { private_access_outcome: "login_required" },
    },
  };
  const { fetch } = mount(value);
  expect(
    await screen.findByRole("button", { name: "Get Tailscale sign-in link" }),
  ).toBeTruthy();
  expect(fetch.mock.calls.some(([p]) => p.endsWith("/link"))).toBe(false);
  fireEvent.click(
    screen.getByRole("button", { name: "Get Tailscale sign-in link" }),
  );
  const link = await screen.findByRole("link", {
    name: "Sign in to Tailscale",
  });
  expect(link.getAttribute("href")).toBe(
    "https://login.tailscale.com/a/PRIVATE-LINK",
  );
  expect(link.getAttribute("referrerpolicy")).toBe("no-referrer");
  expect(fetch).toHaveBeenCalledWith(
    "/api/private-access/actions/login-run/link",
    { cache: "no-store" },
  );
});

it("offers Stop and an inspectable Run while setup is active", async () => {
  const value = { ...base, run: { id: "active-run", status: "running" } };
  const { fetch } = mount(value);
  fireEvent.click(await screen.findByRole("button", { name: "Stop setup" }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith("/api/runs/active-run/cancel", {
      method: "POST",
    }),
  );
  expect(
    screen
      .getByRole("link", { name: "Inspect setup Run" })
      .getAttribute("href"),
  ).toBe("#/runs/active-run");
  expect(
    screen.queryByRole("button", { name: "Start private connection" }),
  ).toBeNull();
});

it("shows the remote link only for the enabled exact approved endpoint", async () => {
  mount({
    ...base,
    enabled: true,
    serving: true,
    state: "Running",
    node_online: true,
    origin,
    approved_origin: origin,
  });
  expect(
    (
      await screen.findByRole("link", { name: "Open AI Station remotely" })
    ).getAttribute("href"),
  ).toBe(origin);
});

it("requires inspection instead of offering another unsafe setup", async () => {
  mount({
    ...base,
    run: {
      id: "lost-run",
      status: "interrupted",
      metadata: { cleanup_requires_inspection: true },
    },
  });
  expect(
    await screen.findByRole("button", { name: "Disable private connection" }),
  ).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: "Start private connection" }),
  ).toBeNull();
});
