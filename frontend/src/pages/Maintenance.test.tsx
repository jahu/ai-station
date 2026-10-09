import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import Maintenance from "./Maintenance";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const readiness = {
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

function mount(fetchImpl: ReturnType<typeof vi.fn>) {
  vi.stubGlobal("fetch", fetchImpl);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <Routes>
          <Route path="/" element={<Maintenance />} />
          <Route path="/runs/:id" element={<h1>Backup Run</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("queues an explicit backup and does not offer restore or rollout", async () => {
  let queued = false;
  const fetch = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/maintenance/backups" && options?.method === "POST") {
      queued = true;
      return {
        ok: true,
        json: async () => ({ id: "run-backup", status: "queued" }),
      };
    }
    if (path === "/api/maintenance/backups") {
      return {
        ok: true,
        json: async () => ({
          restore: "unpublished",
          items: queued
            ? [
                {
                  id: "run-backup",
                  status: "queued",
                  summary: "SQLite backup",
                  restore: "unpublished",
                },
              ]
            : [],
        }),
      };
    }
    return { ok: true, json: async () => readiness };
  });
  mount(fetch);
  await screen.findByRole("heading", { name: "Backup and upgrade readiness" });
  expect(
    screen.queryByRole("button", { name: /restore|rollout|deploy/i }),
  ).toBeNull();
  await screen.findByText(/Restore unpublished/);
  await screen.findByText(/launcher never passes --volumes/);
  fireEvent.click(screen.getByRole("button", { name: "Back up SQLite" }));
  await waitFor(() => expect(queued).toBe(true));
  await screen.findByRole("heading", { name: "Backup Run" });
  expect(
    fetch.mock.calls.some(
      (call) =>
        call[0] === "/api/maintenance/restore" ||
        call[0] === "/api/maintenance/rollout",
    ),
  ).toBe(false);
});

it("marks an interrupted run inspected without posting restore", async () => {
  let acknowledged = false;
  const fetch = vi.fn(async (path: string, options?: RequestInit) => {
    if (path.includes("/acknowledge") && options?.method === "POST") {
      acknowledged = true;
      return {
        ok: true,
        json: async () => ({
          id: "interrupted-run",
          status: "interrupted",
          replay: false,
        }),
      };
    }
    if (path === "/api/maintenance/backups") {
      return {
        ok: true,
        json: async () => ({ restore: "unpublished", items: [] }),
      };
    }
    return {
      ok: true,
      json: async () => ({
        ...readiness,
        interrupted_runs: acknowledged
          ? []
          : [
              {
                id: "interrupted-run",
                title: "Owned photo Run",
                status: "interrupted",
                executor_type: "photo_pipe",
                replay: false,
              },
            ],
      }),
    };
  });
  mount(fetch);
  await screen.findByRole("heading", { name: "Interrupted Runs" });
  fireEvent.click(screen.getByRole("button", { name: "Mark inspected" }));
  await waitFor(() => expect(acknowledged).toBe(true));
  expect(
    fetch.mock.calls
      .map((call) => call[0])
      .filter((path) => String(path).includes("restore")),
  ).toEqual([]);
});
