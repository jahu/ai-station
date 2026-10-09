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

it("re-checks a backup copy without offering restore or rollout", async () => {
  const fetch = vi.fn(async (path: string) => {
    if (path === "/api/maintenance/backups/run-backup") {
      return {
        ok: true,
        json: async () => ({
          run_id: "run-backup",
          status: "succeeded",
          integrity_check: "ok",
          hash_matches: true,
          size_bytes: 12,
          schema_revision: "0019",
          live_schema_revision: "0019",
          schema_matches_live: true,
          restore: "unpublished",
          image_rollout: "unpublished",
          replay: false,
          summary: "Copy integrity_check=ok; restore remains unpublished",
          relative_path: "backups/run-backup.sqlite",
        }),
      };
    }
    if (path === "/api/maintenance/backups") {
      return {
        ok: true,
        json: async () => ({
          restore: "unpublished",
          items: [
            {
              id: "run-backup",
              status: "succeeded",
              summary: "SQLite backup integrity_check=ok",
              restore: "unpublished",
              artifacts: [
                {
                  id: "sqlite-copy",
                  type: "archive",
                  filename: "ai-station.sqlite",
                  size_bytes: 12,
                  relative_path: "backups/run-backup.sqlite",
                },
              ],
              metadata: {
                backup: { integrity_check: "ok", schema_revision: "0019" },
              },
            },
          ],
        }),
      };
    }
    return { ok: true, json: async () => readiness };
  });
  mount(fetch);
  await screen.findByText(/recorded integrity_check=ok/);
  const download = screen.getByRole("link", { name: /Download copy/ });
  expect(download.getAttribute("href")).toBe("/api/artifacts/sqlite-copy/file");
  expect(download.getAttribute("download")).toBe("ai-station.sqlite");
  expect(
    screen.queryByRole("button", { name: /restore|rollout|deploy/i }),
  ).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /Inspect copy/ }));
  await screen.findByText(/matches live schema/);
  await screen.findByText(/backups\/run-backup.sqlite/);
  expect(
    fetch.mock.calls.some(
      (call) =>
        String(call[0]).includes("/restore") ||
        String(call[0]).includes("/rollout"),
    ),
  ).toBe(false);
  expect(
    fetch.mock.calls.filter(
      (call) => call[0] === "/api/maintenance/backups/run-backup",
    ),
  ).toHaveLength(1);
});

it("inspects the running compose image without offering rollout", async () => {
  const fetch = vi.fn(async (path: string) => {
    if (path === "/api/maintenance/image") {
      return {
        ok: true,
        json: async () => ({
          docker: "available",
          runner: "available",
          tag: {
            name: "ai-station:local",
            present: true,
            id: "sha256:abc",
            created: null,
          },
          containers: [
            {
              id: "c".repeat(64),
              name: "ai-station-ai-station-1",
              service: "ai-station",
              project: "ai-station",
              status: "running",
              image: "ai-station:local",
              image_id: "sha256:abc",
              matches_tag: true,
              self: true,
            },
          ],
          matches_running: true,
          restore: "unpublished",
          image_rollout: "unpublished",
          summary:
            "Running control-plane containers use the current ai-station:local image ID.",
        }),
      };
    }
    if (path === "/api/maintenance/backups") {
      return {
        ok: true,
        json: async () => ({ restore: "unpublished", items: [] }),
      };
    }
    return { ok: true, json: async () => readiness };
  });
  mount(fetch);
  fireEvent.click(
    await screen.findByRole("button", { name: "Inspect running image" }),
  );
  await screen.findByText(/this API/);
  await screen.findByText(/matches ai-station:local/);
  await screen.findByText(/present · sha256:abc/);
  expect(
    screen.queryByRole("button", { name: /restore|rollout|deploy/i }),
  ).toBeNull();
  expect(
    fetch.mock.calls
      .map((call) => call[0])
      .filter(
        (path) =>
          String(path).includes("/rollout") ||
          String(path).includes("/restore"),
      ),
  ).toEqual([]);
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
  fireEvent.click(screen.getByRole("button", { name: /Mark inspected/ }));
  await waitFor(() => expect(acknowledged).toBe(true));
  expect(
    fetch.mock.calls
      .map((call) => call[0])
      .filter((path) => String(path).includes("restore")),
  ).toEqual([]);
});

it("moves through backup copies with arrow keys", async () => {
  const copy = {
    status: "succeeded",
    summary: "SQLite backup integrity_check=ok",
    restore: "unpublished",
    artifacts: [
      {
        id: "sqlite-copy",
        type: "archive",
        filename: "ai-station.sqlite",
        size_bytes: 12,
        relative_path: "backups/run.sqlite",
      },
    ],
  };
  mount(
    vi.fn(async (path: string) => {
      if (path === "/api/maintenance/backups") {
        return {
          ok: true,
          json: async () => ({
            restore: "unpublished",
            items: [
              { ...copy, id: "backup01" },
              {
                ...copy,
                id: "backup02",
                artifacts: [{ ...copy.artifacts[0], id: "sqlite-two" }],
              },
            ],
          }),
        };
      }
      return { ok: true, json: async () => readiness };
    }),
  );
  const first = await screen.findByRole("link", {
    name: "Inspect backup Run backup01",
  });
  const second = screen.getByRole("link", {
    name: "Inspect backup Run backup02",
  });
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(screen.getByRole("region", { name: "Recent copies" })).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: /restore|rollout|deploy/i }),
  ).toBeNull();
  fireEvent.keyDown(first.closest(".diagnostic-list") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  expect(document.activeElement).toBe(
    screen
      .getByRole("link", { name: "Inspect backup Run backup02" })
      .closest("[data-list-index]"),
  );
  fireEvent.keyDown(second.closest(".diagnostic-list") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
});

it("moves through interrupted Runs with arrow keys", async () => {
  const row = {
    status: "interrupted",
    executor_type: "photo_pipe",
    replay: false,
  };
  mount(
    vi.fn(async (path: string) => {
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
          interrupted_runs: [
            { ...row, id: "intr-one", title: "Owned photo Run" },
            {
              ...row,
              id: "intr-two",
              title: "Owned chat Run",
              executor_type: "local_chat",
            },
          ],
        }),
      };
    }),
  );
  const first = await screen.findByRole("link", {
    name: "Inspect Owned photo Run intr-one",
  });
  const second = screen.getByRole("link", {
    name: "Inspect Owned chat Run intr-two",
  });
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(screen.getByRole("region", { name: "Interrupted Runs" })).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: /restore|replay|requeue/i }),
  ).toBeNull();
  fireEvent.keyDown(first.closest(".diagnostic-list") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  expect(document.activeElement).toBe(
    screen
      .getByRole("link", { name: "Inspect Owned chat Run intr-two" })
      .closest("[data-list-index]"),
  );
  fireEvent.keyDown(second.closest(".diagnostic-list") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
});
