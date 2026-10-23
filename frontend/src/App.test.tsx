import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
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
        if (url.includes("/coding/sessions")) {
          const session = {
            id: "legacy-session",
            title: "Legacy website",
            project_name: "Saved site",
            status: "succeeded",
            active_run_id: null,
            latest_proposal_id: null,
            runs: [],
          };
          return url.includes("/coding/sessions/legacy-session")
            ? session
            : [session];
        }
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
  expect(screen.getByRole("heading", { name: "Compute" })).toBeTruthy();
  expect(screen.getByRole("region", { name: "Compute" })).toBeTruthy();
  expect(screen.getByRole("meter", { name: "CPU utilization" })).toBeTruthy();
  expect(
    screen.getByRole("navigation", { name: "Quick actions" }),
  ).toBeTruthy();
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
  expect(screen.getByText("Operator session")).toBeTruthy();
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

it("keeps agents primary and loads preserved coding history only through Advanced", async () => {
  mount();
  const main = within(
    screen.getByRole("navigation", { name: "Main navigation" }),
  );
  expect(main.getByRole("link", { name: "Agents" })).toBeTruthy();
  expect(main.queryByRole("link", { name: "Coding" })).toBeNull();
  expect(main.queryByRole("link", { name: "Projects" })).toBeNull();
  expect(
    vi
      .mocked(fetch)
      .mock.calls.some(([url]) => String(url).includes("/coding/sessions")),
  ).toBe(false);
  const trigger = main.getByRole("button", { name: "Advanced workspaces" });
  trigger.focus();
  fireEvent.click(trigger);
  const dialog = within(
    await screen.findByRole("dialog", { name: "Advanced workspaces" }),
  );
  expect(
    dialog.getByRole("link", { name: "Coding" }).getAttribute("href"),
  ).toBe("/coding");
  expect(
    dialog.getByRole("link", { name: "Projects" }).getAttribute("href"),
  ).toBe("/projects");
  expect(
    (await dialog.findByRole("link", { name: "Legacy website" })).getAttribute(
      "href",
    ),
  ).toBe("/coding/legacy-session");
  fireEvent.keyDown(document, { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(document.activeElement).toBe(trigger);
});

it("opens a preserved coding session from Advanced and focuses its workspace", async () => {
  mount();
  fireEvent.click(screen.getByRole("button", { name: "Advanced workspaces" }));
  fireEvent.click(await screen.findByRole("link", { name: "Legacy website" }));
  await screen.findByRole("heading", { name: "Legacy website" });
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  await waitFor(() =>
    expect(document.activeElement).toBe(screen.getByRole("main")),
  );
  expect(document.title).toBe("Coding · AI Station");
});

it("keeps direct project URLs and command-palette access to advanced workspaces", async () => {
  mount("/projects");
  await screen.findByRole("heading", { name: "Projects" });
  expect(
    screen.getByRole("button", { name: "Advanced workspaces" }).className,
  ).toContain("active");
  fireEvent.keyDown(document, { key: "k", ctrlKey: true });
  await screen.findByRole("dialog", { name: "Command palette" });
  expect(
    screen.getByRole("option", { name: /Coding.*Advanced workspace/ }),
  ).toBeTruthy();
  expect(
    screen.getByRole("option", { name: /Projects.*Advanced workspace/ }),
  ).toBeTruthy();
});

it("closing Advanced preserves expanded Chat navigation and returns focus", async () => {
  mount("/chat");
  fireEvent.click(screen.getByRole("button", { name: "Expand navigation" }));
  const trigger = screen.getByRole("button", { name: "Advanced workspaces" });
  trigger.focus();
  fireEvent.click(trigger);
  await screen.findByRole("dialog", { name: "Advanced workspaces" });
  fireEvent.keyDown(document, { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(
    screen
      .getByRole("button", { name: "Collapse navigation" })
      .getAttribute("aria-expanded"),
  ).toBe("true");
  expect(document.activeElement).toBe(trigger);
});
