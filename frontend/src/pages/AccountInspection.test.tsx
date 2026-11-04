import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { AccountContext, type AccountUser } from "../account-context";
import AccountInspection from "./AccountInspection";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const admin: AccountUser = {
  id: "admin",
  username: "Owner",
  display_name: "Owner",
  is_admin: true,
  enabled: true,
  mfa_enabled: true,
  created_at: "2026-10-30T00:00:00Z",
};
const target = {
  ...admin,
  id: "alice",
  username: "Alice",
  display_name: "Alice",
  is_admin: false,
};
const counts = {
  conversations: 1,
  artifacts: 1,
  runs: 1,
  tasks: 1,
  memory: 1,
  agents: 1,
  projects: 1,
  approvals: 1,
  providers: 1,
  connectors: 1,
  creative: 0,
};
const row = {
  id: "record-1",
  title: "A private conversation",
  status: null,
  created_at: admin.created_at,
};
const page = <T,>(
  items: T[],
  total = items.length,
  offset = 0,
  limit = 40,
) => ({ items, total, offset, limit });
const reply = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
function mount(fetch: ReturnType<typeof vi.fn>, user = admin) {
  vi.stubGlobal("fetch", fetch);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const close = vi.fn();
  const view = render(
    <QueryClientProvider client={client}>
      <AccountContext.Provider value={{ mode: "accounts", user }}>
        <AccountInspection target={target} onClose={close} />
      </AccountContext.Provider>
    </QueryClientProvider>,
  );
  return { client, close, ...view };
}
function mockFetch() {
  return vi.fn(async (url: string, options?: RequestInit) => {
    expect(options?.method ?? "GET").toBe("GET");
    expect(url).toContain("/api/admin/users/alice/workspace");
    if (url.endsWith("/workspace"))
      return reply({ user: target, read_only: true, counts, preferences: {} });
    if (url.includes("/entries"))
      return reply(
        page([
          {
            id: "message-1",
            role: "user",
            content: "Private message content",
            created_at: admin.created_at,
          },
        ]),
      );
    if (url.endsWith("/artifacts/record-1"))
      return reply({
        id: row.id,
        title: "Private image",
        mime_type: "image/png",
        created_at: admin.created_at,
      });
    if (url.endsWith("/record-1"))
      return reply({
        id: row.id,
        title: row.title,
        system_prompt: "Private system instructions",
      });
    return reply(page([row]));
  });
}
it("does not open inspection or request any data for a member", () => {
  const fetch = vi.fn();
  mount(fetch, target);
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(fetch).not.toHaveBeenCalled();
});
it("shows explicit subject/actor identities and a read-only conversation transcript", async () => {
  const fetch = mockFetch();
  const { close } = mount(fetch);
  expect(
    screen.getByRole("heading", { name: "Alice’s workspace" }),
  ).toBeTruthy();
  expect(screen.getByText(/You remain signed in as Owner/)).toBeTruthy();
  expect(screen.getByText("Read only")).toBeTruthy();
  fireEvent.click(
    await screen.findByRole("button", { name: /A private conversation/ }),
  );
  expect(await screen.findByText("Private message content")).toBeTruthy();
  expect(screen.getByText("Private system instructions")).toBeTruthy();
  for (const name of [
    "Send",
    "Run now",
    "Stop",
    "Delete",
    "Save",
    "Enable",
    "Approve",
  ]) {
    expect(screen.queryByRole("button", { name })).toBeNull();
  }
  fireEvent.click(
    screen.getByRole("button", { name: "Close workspace inspection" }),
  );
  expect(close).toHaveBeenCalledOnce();
});
it("scopes all categories and media URLs to the selected account", async () => {
  const fetch = mockFetch();
  mount(fetch);
  await screen.findByRole("button", { name: /A private conversation/ });
  for (const [category, title] of [
    ["tasks", "Tasks"],
    ["memory", "Memory"],
    ["agents", "Agents"],
    ["projects", "Projects"],
    ["approvals", "Approvals"],
    ["providers", "Model providers"],
    ["connectors", "Connections"],
    ["runs", "Runs"],
  ]) {
    fireEvent.click(screen.getByRole("button", { name: `${title} (1)` }));
    await waitFor(() =>
      expect(
        fetch.mock.calls.some(([url]) =>
          url.includes(`/workspace/${category}?`),
        ),
      ).toBe(true),
    );
  }
  fireEvent.click(screen.getByRole("button", { name: "Library (1)" }));
  fireEvent.click(
    await screen.findByRole("button", { name: /A private conversation/ }),
  );
  const image = await screen.findByRole("img", { name: "Private image" });
  expect(image.getAttribute("src")).toBe(
    "/api/admin/users/alice/workspace/artifacts/record-1/file",
  );
  expect(
    screen.getByRole("link", { name: "Open file" }).getAttribute("href"),
  ).toBe(image.getAttribute("src"));
  expect(
    fetch.mock.calls.every(
      ([, options]) => (options?.method ?? "GET") === "GET",
    ),
  ).toBe(true);
});
it("clears inspection caches on close without disturbing the actor's own workspace", async () => {
  const { client, unmount } = mount(mockFetch());
  client.setQueryData(["conversations", "admin"], ["own saved workspace"]);
  await screen.findByRole("button", { name: /A private conversation/ });
  expect(
    client.getQueryCache().findAll({ queryKey: ["account-inspection"] }).length,
  ).toBeGreaterThan(0);
  unmount();
  expect(
    client.getQueryCache().findAll({ queryKey: ["account-inspection"] }),
  ).toHaveLength(0);
  expect(client.getQueryData(["conversations", "admin"])).toEqual([
    "own saved workspace",
  ]);
});
it("searches and pages on the server and shows revoked-access errors", async () => {
  const fetch = mockFetch();
  fetch.mockImplementation(async (url, options) => {
    expect(options?.method ?? "GET").toBe("GET");
    if (url.endsWith("/workspace"))
      return reply({ user: target, read_only: true, counts, preferences: {} });
    if (url.includes("search=gone"))
      return reply({ detail: "Administrator access required" }, 403);
    return reply(page([row], 41));
  });
  mount(fetch);
  fireEvent.click(await screen.findByRole("button", { name: "Next records" }));
  await waitFor(() =>
    expect(fetch.mock.calls.some(([url]) => url.includes("offset=40"))).toBe(
      true,
    ),
  );
  fireEvent.change(screen.getByLabelText("Search workspace records"), {
    target: { value: "gone" },
  });
  expect(await screen.findByRole("alert")).toHaveProperty(
    "textContent",
    "Administrator access required",
  );
  expect(
    fetch.mock.calls.some(([url]) => url.includes("offset=0&search=gone")),
  ).toBe(true);
});
