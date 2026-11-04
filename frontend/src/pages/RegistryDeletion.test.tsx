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
import { useRegistryDeletion, type RegistryItem } from "./RegistryDeletion";

const items = [
  { id: "first", name: "Morning report", updated_at: "2026-11-04T10:00:00Z" },
  { id: "second", name: "Weekly summary", updated_at: "2026-11-04T11:00:00Z" },
];
function List({
  rows = items,
  scope = "page1",
  kind = "agents",
}: {
  rows?: RegistryItem[];
  scope?: string;
  kind?: "agents" | "projects";
}) {
  const deletion = useRegistryDeletion(kind, rows, scope);
  return (
    <>
      {deletion.toolbar}
      {rows.map((row) => (
        <div key={row.id}>{deletion.rowActions(row)}</div>
      ))}
      {deletion.dialog}
    </>
  );
}
function mount(props = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <List {...props} />
    </QueryClientProvider>,
  );
  return {
    ...view,
    client,
    update: (next: object) =>
      view.rerender(
        <QueryClientProvider client={client}>
          <List {...next} />
        </QueryClientProvider>,
      ),
  };
}
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("focuses Cancel, names the selection and performs no write on cancel", async () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  mount();
  fireEvent.click(
    screen.getByRole("button", { name: "Delete Morning report" }),
  );
  const dialog = screen.getByRole("dialog", { name: "Delete this agent?" });
  expect(within(dialog).getByText("Morning report")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Cancel" })).toBe(
    document.activeElement,
  );
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  await waitFor(() =>
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Delete Morning report" }),
    ),
  );
  expect(fetch).not.toHaveBeenCalled();
});

it("deletes the selected page only after confirmation and freezes reviewed versions", async () => {
  const fetch = vi.fn(async () => ({
    ok: true,
    json: async () => ({ deleted: 2 }),
  }));
  vi.stubGlobal("fetch", fetch);
  const view = mount();
  fireEvent.click(screen.getByLabelText("Select all agents on this page"));
  fireEvent.click(screen.getByRole("button", { name: "Delete selected (2)" }));
  view.update({
    rows: items.map((row) => ({ ...row, updated_at: "new-version" })),
  });
  fireEvent.click(screen.getByRole("button", { name: "Delete 2 agents" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(fetch).toHaveBeenCalledOnce();
  const [path, options] = fetch.mock.calls[0] as unknown as [
    string,
    RequestInit,
  ];
  expect(path).toBe("/api/agents/delete");
  expect(JSON.parse(options.body as string)).toEqual({
    confirmed: true,
    items: items.map(({ id, updated_at }) => ({
      id,
      expected_updated_at: updated_at,
    })),
  });
  expect(
    screen.queryByRole("button", { name: "Delete selected (2)" }),
  ).toBeNull();
});

it("keeps active-work errors visible with an available cancel action", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: false,
      status: 409,
      json: async () => ({
        detail: "Stop or finish active work before deleting this selection.",
      }),
    })),
  );
  mount();
  fireEvent.click(
    screen.getByRole("button", { name: "Delete Morning report" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Delete agent" }));
  await screen.findByText(
    "Stop or finish active work before deleting this selection.",
  );
  expect(screen.getByRole("dialog")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("does not carry page selection across filters and explains project files are kept", () => {
  const view = mount();
  fireEvent.click(screen.getByLabelText("Select Morning report"));
  view.update({ scope: "page2", kind: "projects" });
  expect(screen.queryByRole("button", { name: /Delete selected/ })).toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "Delete Morning report" }),
  );
  expect(
    screen.getByText(
      /Original folders, repositories and worktrees stay on disk/,
    ),
  ).toBeTruthy();
});
