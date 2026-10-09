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
    screen.queryByRole("button", { name: /bind|publish|lan/i }),
  ).toBeNull();
  fireEvent.click(skip);
  expect(document.activeElement).toBe(screen.getByRole("main"));
});

it("opens the command palette from Control K and focuses the workspace after going home", async () => {
  mount("/not-a-workspace");
  fireEvent.keyDown(document, { key: "k", ctrlKey: true });
  const dialog = await screen.findByRole("dialog");
  expect(dialog).toBeTruthy();
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
