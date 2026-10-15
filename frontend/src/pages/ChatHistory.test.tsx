import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import Chat from "./Chat";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  sessionStorage.clear();
});
it("loads older conversations with a cursor and searches saved message history", async () => {
  const requests: string[] = [];
  const row = (n: number) => ({
    id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
    title: `Chat ${n}`,
    model: "plain",
    updated_at: "2026-10-14T10:00:00Z",
  });
  const hundred = Array.from({ length: 100 }, (_, n) => row(n));
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      requests.push(url);
      let value: unknown = [];
      if (url.includes("/chat/conversations"))
        value = url.includes("q=telescope")
          ? [{ ...row(101), title: "Telescope decision" }]
          : url.includes("before_id")
            ? [row(100), row(101)]
            : hundred;
      else if (url.endsWith("/chat/providers"))
        value = [
          {
            key: "local-openai-compatible",
            builtin: true,
            enabled: true,
            location: "local",
            default_model: "plain",
            models: ["plain"],
            secret_source: "none",
            secret_present: false,
          },
        ];
      else if (url.includes("/chat/providers/"))
        value = {
          key: "local-openai-compatible",
          enabled: true,
          location: "local",
          default_model: "plain",
          models: ["plain"],
          secret_source: "none",
          secret_present: false,
        };
      else if (url.includes("model-catalog"))
        value = { models: [], providers: [] };
      else if (url.includes("preferences"))
        value = {
          version: 0,
          mode: "chat",
          provider: "local-openai-compatible",
          model: "plain",
          send_key: "enter",
        };
      return { ok: true, json: async () => value };
    }),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <Chat />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByRole("link", { name: /Inspect Chat 99/ });
  fireEvent.click(screen.getByText("Recent conversations"));
  fireEvent.click(
    screen.getByRole("button", { name: "Load older conversations" }),
  );
  await screen.findByRole("link", { name: /Inspect Chat 101/ });
  expect(requests.some((url) => url.includes("before_id="))).toBe(true);
  expect(
    screen.queryByRole("button", { name: "Load older conversations" }),
  ).toBeNull();
  fireEvent.change(
    screen.getByRole("searchbox", { name: "Search conversations" }),
    { target: { value: "telescope" } },
  );
  await screen.findByRole("link", { name: /Inspect Telescope decision/ });
  expect(screen.queryByRole("link", { name: /Inspect Chat 99/ })).toBeNull();
  // Rendering and querying 100+ accessible cards needs a bounded integration
  // budget on the workstation while backend/media checks share its CPUs.
}, 15_000);
