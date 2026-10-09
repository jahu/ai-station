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
import App from "./App";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  document.title = "AI Station · Your AI workstation";
});

function mount(path = "/home") {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  Element.prototype.scrollIntoView = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => ({
      ok: true,
      json: async () => {
        const url = String(path);
        if (url.includes("/dashboard")) {
          return {
            active_run_count: 0,
            enabled_agent_count: 0,
            active_runs: [],
            upcoming: [],
            agents: [],
            conversations: [],
            artifacts: [],
            runtimes: [],
            notices: [],
            interrupted_runs: [],
          };
        }
        if (url.includes("/system/hardware")) {
          return {
            gpus: [],
            cpu: { utilization: null, temperature_c: null },
            memory: {
              total_mib: 1,
              used_mib: 0,
              available_mib: 1,
              swap_used_mib: 0,
              swap_total_mib: 0,
            },
            disk: { total_bytes: 1, used_bytes: 0, free_bytes: 1 },
            load: {},
          };
        }
        if (url.includes("/system/status")) {
          return {
            scheduler: { available: false, last_heartbeat: null },
            worker: { available: false, last_heartbeat: null },
          };
        }
        if (url.includes("/operator-auth")) {
          return {
            configured: false,
            session_required: false,
            authenticated: false,
            lan_bind_allowed: false,
            bind_host: "127.0.0.1",
            lan_exposure: "disabled",
            reason: "loopback",
          };
        }
        return [];
      },
    })),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("skips to the workspace without opening LAN publish", async () => {
  mount("/home");
  const skip = await screen.findByRole("link", { name: "Skip to workspace" });
  expect(screen.getByRole("main")).toBeTruthy();
  expect(document.title).toBe("Home · AI Station");
  expect(document.getElementById("route-announcer")?.textContent).toBe("");
  expect(
    screen.queryByRole("button", { name: /bind|publish|lan|sign out/i }),
  ).toBeNull();
  fireEvent.click(skip);
  expect(document.activeElement).toBe(screen.getByRole("main"));
});

it("signs out the loopback session from chrome without offering LAN publish", async () => {
  let authenticated = true;
  const fetch = vi.fn(async (path: string, options?: RequestInit) => {
    const url = String(path);
    if (url.includes("/operator-auth/logout") && options?.method === "POST") {
      authenticated = false;
      return {
        ok: true,
        json: async () => ({
          configured: true,
          session_required: true,
          authenticated: false,
          session_scope: "loopback",
          lan_bind_allowed: false,
          bind_host: "127.0.0.1",
          lan_exposure: "unpublished",
          reason: "loopback",
        }),
      };
    }
    if (url.includes("/operator-auth")) {
      return {
        ok: true,
        json: async () => ({
          configured: true,
          session_required: true,
          authenticated,
          session_scope: "loopback",
          lan_bind_allowed: false,
          bind_host: "127.0.0.1",
          lan_exposure: "unpublished",
          reason: "loopback",
        }),
      };
    }
    if (url.includes("/dashboard")) {
      return {
        ok: true,
        json: async () => ({
          active_run_count: 0,
          enabled_agent_count: 0,
          active_runs: [],
          upcoming: [],
          agents: [],
          conversations: [],
          artifacts: [],
          runtimes: [],
          notices: [],
          interrupted_runs: [],
        }),
      };
    }
    if (url.includes("/system/hardware")) {
      return {
        ok: true,
        json: async () => ({
          gpus: [],
          cpu: { utilization: null, temperature_c: null },
          memory: {
            total_mib: 1,
            used_mib: 0,
            available_mib: 1,
            swap_used_mib: 0,
            swap_total_mib: 0,
          },
          disk: { total_bytes: 1, used_bytes: 0, free_bytes: 1 },
          load: {},
        }),
      };
    }
    return {
      ok: true,
      json: async () =>
        url.includes("/system/status")
          ? {
              scheduler: { available: false, last_heartbeat: null },
              worker: { available: false, last_heartbeat: null },
            }
          : [],
    };
  });
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  Element.prototype.scrollIntoView = vi.fn();
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={["/home"]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const signOut = await screen.findByRole("button", { name: "Sign out" });
  expect(screen.getByText("Loopback session")).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: /bind|publish|lan/i }),
  ).toBeNull();
  fireEvent.click(signOut);
  await waitFor(() => expect(authenticated).toBe(false));
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: "Sign out" })).toBeNull(),
  );
  expect(
    fetch.mock.calls.some(
      (call) =>
        String(call[0]).includes("/operator-auth/logout") &&
        (call[1] as RequestInit | undefined)?.method === "POST",
    ),
  ).toBe(true);
});

it("opens the command palette from Control K and focuses the workspace after going home", async () => {
  mount("/not-a-workspace");
  fireEvent.keyDown(document, { key: "k", ctrlKey: true });
  const dialog = await screen.findByRole("dialog", { name: "Command palette" });
  expect(dialog).toBeTruthy();
  expect(screen.getByLabelText("Search workspaces and actions")).toBeTruthy();
  fireEvent.click(screen.getByRole("option", { name: /Home activity/ }));
  await waitFor(() =>
    expect(
      screen.getByRole("heading", { name: /Needs attention/ }),
    ).toBeTruthy(),
  );
  expect(document.activeElement).toBe(screen.getByRole("main"));
  expect(document.title).toBe("Home · AI Station");
  expect(document.getElementById("route-announcer")?.textContent).toBe(
    "Home workspace",
  );
});
