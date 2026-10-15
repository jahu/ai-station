import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { GithubConnectors } from "./GithubConnectors";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function show(rows: Parameters<typeof GithubConnectors>[0]["rows"]) {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <GithubConnectors rows={rows} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("connects a repository without copying credentials or starting a refresh", async () => {
  const writes: { path: string; body: Record<string, unknown> }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      writes.push({ path, body: JSON.parse(String(init?.body)) });
      return { ok: true, json: async () => ({ id: "new" }) };
    }),
  );
  show([]);
  fireEvent.change(screen.getByRole("textbox", { name: "GitHub repository" }), {
    target: { value: "owner/repo" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Connect repository" }));
  await vi.waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0].path).toBe("/api/connectors");
  expect(writes[0].body).toEqual({
    kind: "github",
    repository: "owner/repo",
    name: "owner/repo",
    key: expect.stringMatching(/^github-/),
  });
});

it("shows a stored snapshot and refreshes in place", async () => {
  const calls: string[] = [];
  const row = {
    id: "repo-id",
    repository: "owner/repo",
    name: "Our project",
    status: "ready",
    last_run_id: "last-run",
    enabled: true,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "POST") calls.push(path);
      return {
        ok: true,
        json: async () =>
          path.endsWith("/check")
            ? { id: "next-run" }
            : {
                connector: row,
                snapshot: {
                  captured_at: "2026-10-15T10:00:00Z",
                  artifact_id: "snapshot-file",
                  project: {
                    name: "owner/repo",
                    description: "Our application",
                    url: "https://github.com/owner/repo",
                    private: true,
                    default_branch: "develop",
                  },
                  issues: [
                    {
                      number: 12,
                      title: "Fix login",
                      url: "https://github.com/owner/repo/issues/12",
                      author: "owner",
                    },
                  ],
                  pull_requests: [],
                },
              },
      };
    }),
  );
  show([row]);
  const issue = await screen.findByRole("link", { name: "#12 Fix login" });
  expect(issue.getAttribute("href")).toBe(
    "https://github.com/owner/repo/issues/12",
  );
  expect(
    screen
      .getByRole("link", { name: "Download snapshot" })
      .getAttribute("href"),
  ).toBe("/api/artifacts/snapshot-file/file");
  fireEvent.click(screen.getByRole("button", { name: "Refresh repository" }));
  await vi.waitFor(() =>
    expect(calls).toEqual(["/api/connectors/repo-id/check"]),
  );
  expect(
    screen.getByRole("article", { name: "GitHub owner/repo" }),
  ).toBeTruthy();
});

it("keeps the previous snapshot visible when the latest refresh fails", async () => {
  const row = {
    id: "repo-id",
    repository: "owner/repo",
    name: "Our project",
    status: "failed",
    last_run_id: "failed-run",
    enabled: true,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({
        connector: row,
        refresh_error: "GitHub read failed; check host login",
        snapshot: {
          captured_at: "2026-10-15T10:00:00Z",
          artifact_id: "old",
          project: {
            name: "owner/repo",
            description: "Last known observation",
            private: true,
            default_branch: "develop",
          },
          issues: [],
          pull_requests: [],
        },
      }),
    })),
  );
  show([row]);
  expect(await screen.findByText("Last known observation")).toBeTruthy();
  expect(screen.getByRole("alert").textContent).toContain("check host login");
  expect(
    screen.getByRole("link", { name: "Inspect refresh" }).getAttribute("href"),
  ).toBe("/runs/failed-run");
});

it("fetches the finished snapshot when refresh status changes before the next poll", async () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  let finished = false;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({
        snapshot: {
          captured_at: "2026-10-15T12:00:00Z",
          artifact_id: "snapshot",
          project: {
            name: "owner/repo",
            description: finished ? "New observation" : "Old observation",
            private: true,
            default_branch: "develop",
          },
          issues: [],
          pull_requests: [],
        },
      }),
    })),
  );
  const tree = (status: string) => (
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <GithubConnectors
          rows={[
            {
              id: "repo",
              name: "Our project",
              repository: "owner/repo",
              status,
              last_run_id: "same-refresh",
              enabled: true,
            },
          ]}
        />
      </MemoryRouter>
    </QueryClientProvider>
  );
  const view = render(tree("checking"));
  await screen.findByText("Old observation");
  finished = true;
  view.rerender(tree("ready"));
  await screen.findByText("New observation");
});
