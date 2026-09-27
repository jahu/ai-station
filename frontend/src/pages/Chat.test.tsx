import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import Chat from "./Chat";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("creates a conversation with explicit local model settings", async () => {
  const fetch = vi.fn(async (path: string, options?: RequestInit) => ({
    ok: true,
    json: async () =>
      path.endsWith("/provider")
        ? {
            models: ["test-model"],
            default_model: "test-model",
            endpoint: "http://localhost:8080/v1",
            location: "local",
          }
        : path.endsWith("/llama")
          ? { models: [], instances: [] }
          : path.endsWith("/hardware")
            ? { gpus: [] }
            : options?.method === "POST"
              ? { id: "new" }
              : [],
  }));
  vi.stubGlobal("fetch", fetch);
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={cache}>
      <MemoryRouter initialEntries={["/chat"]}>
        <Routes>
          <Route path="/chat" element={<Chat />} />
          <Route path="/chat/new" element={<h1>Created chat</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByLabelText("Model");
  fireEvent.change(screen.getByLabelText("System prompt"), {
    target: { value: "Explain clearly" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Create conversation" }));
  await screen.findByRole("heading", { name: "Created chat" });
  expect(fetch).toHaveBeenCalledWith(
    "/api/chat/conversations",
    expect.objectContaining({
      body: expect.stringContaining('"system_prompt":"Explain clearly"'),
    }),
  );
});
