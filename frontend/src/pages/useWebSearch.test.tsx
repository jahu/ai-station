import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useWebSearch, type ChatPreferences } from "./useWebSearch";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function mount(allowed = true) {
  function Composer() {
    const web = useWebSearch(allowed);
    return (
      <button disabled={web.busy} onClick={() => web.onToggle(!web.enabled)}>
        {web.enabled ? "Online" : "Offline"}
      </button>
    );
  }
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <Composer />
    </QueryClientProvider>,
  );
}

it("starts online and remembers an explicit opt-out after a fresh conversation/cache", async () => {
  let saved: ChatPreferences = {
    version: 0,
    mode: "chat",
    provider: "local",
    model: "fixture",
    send_key: "enter",
    web_search_enabled: true,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_path: string, init?: RequestInit) => {
      if (init?.method === "PUT") {
        const body = JSON.parse(String(init.body));
        expect(body.version).toBe(saved.version);
        expect(body.model).toBe("fixture");
        saved = { ...body, version: saved.version + 1 };
      }
      return { ok: true, json: async () => saved };
    }),
  );
  mount();
  const online = await screen.findByRole("button", { name: "Online" });
  await vi.waitFor(() => expect(online.hasAttribute("disabled")).toBe(false));
  fireEvent.click(online);
  await vi.waitFor(() => expect(saved.web_search_enabled).toBe(false));
  cleanup();
  mount();
  const offline = await screen.findByRole("button", { name: "Offline" });
  await vi.waitFor(() => expect(offline.hasAttribute("disabled")).toBe(false));
  fireEvent.click(offline);
  await vi.waitFor(() => expect(saved.web_search_enabled).toBe(true));
});

it("does not apply the Chat default to Work or coding continuation scopes", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({ web_search_enabled: true }),
    })),
  );
  mount(false);
  const button = await screen.findByRole("button", { name: "Offline" });
  await vi.waitFor(() => expect(button.hasAttribute("disabled")).toBe(false));
  expect(screen.queryByText("Online")).toBeNull();
});
