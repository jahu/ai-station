import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import System from "./System";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("lists expired leases without offering replay or restore", async () => {
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
        if (url.includes("/system/diagnostics")) return { checks: [] };
        if (url.includes("/system/status")) {
          return {
            counts: {},
            workers: [],
            scheduler: { available: false, last_heartbeat: null },
            lease_seconds: 45,
            held_lease_count: 1,
            stale_lease_count: 1,
            leases: [
              {
                id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                status: "running",
                worker_id: "w1",
                executor_type: "fake",
                retry_class: "inspect",
                lease_expires_at: "2026-10-09T12:00:00Z",
                stale: true,
                replay: false,
              },
            ],
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
    screen.getByRole("link", { name: "aaaaaaaa" }).getAttribute("href"),
  ).toBe("/runs/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee");
  expect(screen.getByText(/replay no/)).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: /replay|restore|requeue|rollout/i }),
  ).toBeNull();
});
