import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import Chat from "./Chat";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const builtin = {
  id: "builtin-id",
  key: "local-openai-compatible",
  name: "Local OpenAI-compatible",
  kind: "openai-compatible",
  location: "local",
  endpoint: "http://localhost:8080/v1",
  default_model: "test-model",
  builtin: true,
  enabled: true,
  secret_source: "none",
  secret_ref: "",
  secret_present: false,
  models: ["test-model"],
  status: "available",
  error: null,
};

it("creates a conversation with explicit local model settings", async () => {
  const fetch = vi.fn(async (path: string, options?: RequestInit) => ({
    ok: true,
    json: async () =>
      path.endsWith("/chat/providers")
        ? [builtin]
        : path.includes("/chat/providers/")
          ? builtin
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
  expect(screen.getByLabelText("Mode")).toBeTruthy();
  expect(screen.getByLabelText("Conversation title")).toBeTruthy();
  expect(screen.getByLabelText("Provider")).toBeTruthy();
  expect(screen.getByLabelText("Temperature")).toBeTruthy();
  expect(screen.getByLabelText("Maximum tokens")).toBeTruthy();
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
  expect(fetch).toHaveBeenCalledWith(
    "/api/chat/conversations",
    expect.objectContaining({
      body: expect.stringContaining('"provider":"local-openai-compatible"'),
    }),
  );
});
