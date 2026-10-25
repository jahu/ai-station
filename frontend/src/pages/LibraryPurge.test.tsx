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
import type { Artifact } from "../api";
import { PurgeActivity, PurgeButton } from "./LibraryPurge";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const artifact: Artifact = {
  id: "a",
  type: "image",
  mime_type: "image/png",
  original_filename: "portrait.png",
  size_bytes: 100,
  created_at: "2026-10-25T12:00:00Z",
  run_id: null,
  parent_artifact_ids: [],
  metadata: {},
  library_updated_at: "2026-10-25T12:01:00Z",
};
const item = {
  id: artifact.id,
  name: artifact.original_filename,
  version: artifact.library_updated_at,
};
const run = {
  id: "delete-run",
  status: "waiting_for_approval",
  parameters: { items: [item], scope: "selected" },
  metadata: {},
};
function mount(element: React.ReactNode) {
  render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
          },
        })
      }
    >
      <MemoryRouter>{element}</MemoryRouter>
    </QueryClientProvider>,
  );
}
const response = (value: unknown) => ({ ok: true, json: async () => value });

it("limits contextual progress to the inspected artifact", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      response([
        {
          ...run,
          id: "unrelated",
          status: "queued",
          parameters: { items: [{ id: "b", name: "other" }] },
        },
        { ...run, status: "queued" },
      ]),
    ),
  );
  mount(<PurgeActivity artifactId="a" />);
  const links = await screen.findAllByRole("link", {
    name: "Inspect execution history",
  });
  expect(links).toHaveLength(1);
  expect(links[0].getAttribute("href")).toBe("/runs/delete-run");
});

it("an unconfirmed deletion can be reviewed after a page reload", async () => {
  const fetch = vi.fn(async (path: string) =>
    response(path === "/api/library/purges" ? [run] : run),
  );
  vi.stubGlobal("fetch", fetch);
  mount(<PurgeActivity />);
  await screen.findByText("Deletion awaiting confirmation");
  fireEvent.click(screen.getByRole("button", { name: "Review deletion" }));
  await screen.findByRole("dialog", { name: "Delete permanently?" });
  expect(
    fetch.mock.calls.filter(([path]) => path === "/api/library/purges"),
  ).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "Keep files" }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/runs/delete-run/approval",
      expect.objectContaining({
        body: JSON.stringify({ resolution: "denied" }),
      }),
    ),
  );
});

it("a lost approval response is reconciled against the original Run", async () => {
  const fetch = vi.fn(async (path: string) => {
    if (path.endsWith("/approval")) throw new Error("Lost response");
    return response(
      path === "/api/runs/delete-run"
        ? { ...run, status: "queued", approval: { resolution: "granted" } }
        : run,
    );
  });
  vi.stubGlobal("fetch", fetch);
  mount(<PurgeButton artifacts={[artifact]} />);
  fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
  const dialog = await screen.findByRole("dialog", {
    name: "Delete permanently?",
  });
  await within(dialog).findByText("portrait.png");
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Delete permanently" }),
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(fetch).toHaveBeenCalledWith("/api/runs/delete-run", undefined);
});

it("prepares an immutable selection and grants only on the destructive confirmation", async () => {
  const fetch = vi.fn(async () => response(run));
  vi.stubGlobal("fetch", fetch);
  mount(<PurgeButton artifacts={[artifact]} />);
  fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
  const dialog = await screen.findByRole("dialog", {
    name: "Delete permanently?",
  });
  await within(dialog).findByText("portrait.png");
  expect(fetch).toHaveBeenCalledTimes(1);
  const [path, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
  expect(path).toBe("/api/library/purges");
  expect(JSON.parse(String(init.body))).toMatchObject({
    scope: "selected",
    items: [{ id: "a", expected_updated_at: artifact.library_updated_at }],
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Delete permanently" }),
  );
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/runs/delete-run/approval",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ resolution: "granted" }),
      }),
    ),
  );
});

it("Empty Trash confirms the server's full count, independent of the displayed count", async () => {
  const fetch = vi.fn(async () =>
    response({
      ...run,
      parameters: {
        items: [
          item,
          { ...item, id: "b", name: "voice.wav" },
          { ...item, id: "c", name: "video.mp4" },
        ],
        scope: "trash",
      },
    }),
  );
  vi.stubGlobal("fetch", fetch);
  mount(<PurgeButton emptyTrash count={1} />);
  fireEvent.click(screen.getByRole("button", { name: "Empty Trash (1)" }));
  await screen.findByText("3 artifacts");
  expect(
    screen.getByText(/complete Trash, across every page and filter/),
  ).toBeTruthy();
  const init = (fetch.mock.calls[0] as unknown as [string, RequestInit])[1];
  expect(JSON.parse(String(init.body))).toMatchObject({
    scope: "trash",
    items: [],
  });
  fireEvent.click(screen.getByRole("button", { name: "Keep files" }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/runs/delete-run/approval",
      expect.objectContaining({
        body: JSON.stringify({ resolution: "denied" }),
      }),
    ),
  );
});

it("a failed prepare retry retains the receipt identity", async () => {
  const fetch = vi
    .fn()
    .mockRejectedValueOnce(new Error("Connection interrupted"))
    .mockResolvedValue(response(run));
  vi.stubGlobal("fetch", fetch);
  mount(<PurgeButton artifacts={[artifact]} />);
  fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
  await screen.findByText("Connection interrupted");
  fireEvent.click(screen.getByRole("button", { name: "Retry preparing" }));
  await screen.findByText("portrait.png");
  expect(JSON.parse(fetch.mock.calls[0][1].body).request_id).toBe(
    JSON.parse(fetch.mock.calls[1][1].body).request_id,
  );
});

it("partial results show exact failures and retry only remaining artifact identities", async () => {
  const partial = {
    ...run,
    status: "failed",
    parameters: {
      items: [item, { ...item, id: "b", name: "voice.wav" }],
      scope: "trash",
    },
    metadata: {
      purge_outcomes: {
        a: { state: "deleted" },
        b: { state: "failed", error: "Disk error" },
      },
    },
  };
  const fetch = vi.fn(async (path: string) =>
    response(
      path === "/api/library/purges"
        ? [partial]
        : { ...artifact, id: "b", original_filename: "voice.wav" },
    ),
  );
  vi.stubGlobal("fetch", fetch);
  mount(<PurgeActivity />);
  await screen.findByText("1 of 2 deleted · 1 failed · 1 remain");
  fireEvent.click(screen.getByText("Files that could not be deleted"));
  expect(screen.getByText("voice.wav: Disk error")).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", { name: "Review remaining files" }),
  );
  await screen.findByRole("button", { name: "Delete permanently" });
  expect(fetch).toHaveBeenCalledWith("/api/artifacts/b", undefined);
  expect(fetch).not.toHaveBeenCalledWith("/api/artifacts/a", undefined);
});
