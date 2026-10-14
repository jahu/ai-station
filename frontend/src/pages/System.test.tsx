import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import System from "./System";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const lease = {
  status: "running",
  worker_id: "w1",
  executor_type: "fake",
  retry_class: "inspect",
  lease_expires_at: "2026-10-09T12:00:00Z",
  stale: true,
  replay: false,
};

function mount(
  leases: Array<typeof lease & { id: string }>,
  extras: {
    checks?: { name: string; status: string; detail: string }[];
    workers?: { id: string; available: boolean; last_heartbeat: string }[];
  } = {},
) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => ({
      ok: true,
      json: async () => {
        const url = String(path);
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
        if (url.includes("/system/gpu-processes"))
          return {
            status: "unavailable",
            sampled_at: null,
            processes: [],
            truncated: false,
          };
        if (url.includes("/system/diagnostics"))
          return { checks: extras.checks ?? [] };
        if (url.includes("/system/status")) {
          return {
            counts: {},
            workers: extras.workers ?? [],
            scheduler: { available: false, last_heartbeat: null },
            lease_seconds: 45,
            held_lease_count: leases.length,
            stale_lease_count: leases.filter((row) => row.stale).length,
            leases,
          };
        }
        if (url.includes("/operator-auth")) {
          return {
            configured: false,
            bind_host: "127.0.0.1",
            lan_exposure: "unpublished",
            lan_bind_allowed: false,
            reason: "The UI/API stays on loopback. LAN publish is not enabled.",
          };
        }
        if (url.includes("/nodes")) {
          return {
            items: [],
            remote_registration: "unpublished",
            lan_exposure: "unpublished",
            summary: "",
          };
        }
        if (url.includes("/maintenance/backups")) {
          return { items: [], restore: "unpublished" };
        }
        if (url.includes("/maintenance")) {
          return {
            schema_revision: "0019",
            schema_head: "0019",
            schema_current_matches_head: true,
            database: "db/ai-station.sqlite",
            journal_mode: "wal",
            active_runs: 0,
            upgrade_blocked_by_active_runs: false,
            data_survives_compose_down: true,
            compose_down_removes_bind_data: false,
            application_data: "bind-mount",
            restore: "unpublished",
            image_rollout: "unpublished",
            lan_bind_allowed: false,
            last_backup: null,
            interrupted_runs: [],
            summary: "Upgrade readiness is inspect-only.",
          };
        }
        if (url.includes("/chat/providers")) return [];
        if (url.includes("/connectors")) return [];
        if (url.includes("/runtimes")) {
          return { items: [], total: 0, latest_scan: null };
        }
        return {};
      },
    })),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <System />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("lists expired leases without offering replay or restore", async () => {
  mount([{ ...lease, id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" }]);
  expect(
    await screen.findByText(/expired lease waiting for a worker tick/i),
  ).toBeTruthy();
  expect(screen.getByText("Held leases")).toBeTruthy();
  expect(
    screen.getByText(
      /No available worker is registered, so recovery is paused/,
    ),
  ).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "Inspect aaaaaaaa" }).getAttribute("href"),
  ).toBe("/runs/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee");
  expect(screen.getByText(/replay no/)).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: /replay|restore|requeue|rollout/i }),
  ).toBeNull();
});

it("moves through worker leases with arrow keys", async () => {
  mount([
    { ...lease, id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" },
    {
      ...lease,
      id: "bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
      stale: false,
      replay: false,
    },
  ]);
  const first = await screen.findByRole("link", { name: "Inspect aaaaaaaa" });
  const second = screen.getByRole("link", { name: "Inspect bbbbbbbb" });
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(screen.getByRole("region", { name: "Worker leases" })).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: /replay|restore|requeue|rollout/i }),
  ).toBeNull();
  fireEvent.keyDown(first.closest(".diagnostic-list") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  expect(document.activeElement).toBe(
    screen
      .getByRole("link", { name: "Inspect bbbbbbbb" })
      .closest("[data-list-index]"),
  );
  fireEvent.keyDown(second.closest(".diagnostic-list") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
});

it("moves through integration checks with arrow keys", async () => {
  mount([], {
    checks: [
      {
        name: "Docker",
        status: "available",
        detail: "Engine is reachable.",
      },
      {
        name: "GPU",
        status: "unavailable",
        detail: "No discovered GPU.",
      },
    ],
  });
  const first = await screen.findByLabelText("Check Docker");
  const second = screen.getByLabelText("Check GPU");
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(
    screen.getByRole("region", { name: "Integration checks" }),
  ).toBeTruthy();
  expect(
    screen.getByText(/There is no inspectable diagnostic Run/),
  ).toBeTruthy();
  fireEvent.keyDown(first.closest(".diagnostic-list") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  expect(document.activeElement).toBe(second);
  fireEvent.keyDown(second.closest(".diagnostic-list") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
});

it("moves through worker heartbeats with arrow keys", async () => {
  mount([], {
    workers: [
      {
        id: "worker-one",
        available: true,
        last_heartbeat: "2026-10-09T12:00:00Z",
      },
      {
        id: "worker-two",
        available: false,
        last_heartbeat: "2026-10-09T11:00:00Z",
      },
    ],
  });
  const first = await screen.findByLabelText("Worker worker-one");
  const second = screen.getByLabelText("Worker worker-two");
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(
    screen.getByRole("region", { name: "Worker heartbeats" }),
  ).toBeTruthy();
  expect(
    screen.getByText(/There is no inspectable heartbeat Run/),
  ).toBeTruthy();
  fireEvent.keyDown(first.closest(".diagnostic-list") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  expect(document.activeElement).toBe(second);
  fireEvent.keyDown(second.closest(".diagnostic-list") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
});
