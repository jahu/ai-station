import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import Settings from "./Settings";
import { SystemRoute } from "./System";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const provider = {
  key: "local-openai-compatible",
  id: "local",
  name: "Local server",
  builtin: true,
  location: "local",
  enabled: true,
  default_model: "test-model",
  models: ["test-model"],
  secret_source: "none",
  secret_present: false,
  status: "available",
};

function mount(path = "/settings") {
  const writes: { path: string; body: Record<string, unknown> }[] = [];
  let preferences = {
    version: 3,
    mode: "chat",
    provider: provider.key,
    model: "test-model",
    send_key: "enter",
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method && init.method !== "GET") {
        const body = JSON.parse(String(init.body));
        writes.push({ path: url, body });
        preferences = { ...body, version: body.version + 1 };
        return { ok: true, json: async () => preferences };
      }
      return {
        ok: true,
        json: async () =>
          url.endsWith("/chat/preferences")
            ? preferences
            : url.endsWith("/chat/providers")
              ? [provider]
              : url.includes("/chat/providers/")
                ? provider
                : url.endsWith("/llama")
                  ? { models: [], instances: [] }
                  : url.includes("/hardware")
                    ? { gpus: [] }
                    : [],
      };
    }),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/settings" element={<Settings />} />
          <Route path="/settings/:section" element={<Settings />} />
          <Route path="/system" element={<SystemRoute />} />
          <Route
            path="/system/diagnostics"
            element={<h1>Diagnostics page</h1>}
          />
          <Route
            path="/settings/maintenance"
            element={<h1>Maintenance settings</h1>}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return writes;
}

it("opens dedicated General settings without launching work", async () => {
  const writes = mount();
  await screen.findByRole("heading", { name: "New conversations" });
  expect(
    screen.getByRole("navigation", { name: "Settings sections" }),
  ).toBeTruthy();
  expect(
    screen.queryByRole("heading", { name: "Workstation status" }),
  ).toBeNull();
  expect(writes).toHaveLength(0);
  fireEvent.click(screen.getByRole("link", { name: "Providers" }));
  await screen.findByRole("heading", { name: "Chat providers", level: 2 });
  expect(writes).toHaveLength(0);
});

it("saves typed defaults and send preference without submitting a Run", async () => {
  const writes = mount("/settings/general");
  await screen.findByRole("button", { name: "Save preferences" });
  fireEvent.click(screen.getByRole("button", { name: "Work" }));
  fireEvent.change(screen.getByLabelText("Send message with"), {
    target: { value: "ctrl-enter" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save preferences" }));
  await screen.findByRole("status");
  expect(writes).toEqual([
    {
      path: "/api/chat/preferences",
      body: {
        version: 3,
        mode: "work",
        provider: provider.key,
        model: "test-model",
        send_key: "ctrl-enter",
      },
    },
  ]);
  fireEvent.click(screen.getByRole("button", { name: "Chat" }));
  expect(screen.queryByText("Preferences saved")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Save preferences" }));
  await vi.waitFor(() => expect(writes).toHaveLength(2));
  expect(writes[1].body).toMatchObject({ version: 4, mode: "chat" });
});

it("redirects the existing System maintenance bookmark to its canonical Settings page", async () => {
  const writes = mount("/system?focus=maintenance");
  await screen.findByRole("heading", { name: "Maintenance settings" });
  expect(writes).toHaveLength(0);
});
