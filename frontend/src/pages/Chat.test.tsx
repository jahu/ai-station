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

it("moves through conversation messages with arrow keys", async () => {
  const conversation = {
    id: "conv",
    title: "Planning",
    provider: "local-openai-compatible",
    provider_name: "Local OpenAI-compatible",
    provider_location: "local",
    model: "test-model",
    system_prompt: "",
    temperature: 0.7,
    max_tokens: 2048,
    updated_at: "2026-10-09T12:00:00Z",
    execution_mode: "local",
    auto_summary: false,
    summary_update: null,
    summary: null,
    active_run: null,
    messages: [
      {
        id: "user-one",
        role: "user",
        content: "Hello",
        created_at: "2026-10-09T12:00:00Z",
        run_id: null,
        run_status: null,
        error_message: "",
        metadata: {},
      },
      {
        id: "asst-two",
        role: "assistant",
        content: "Hi there",
        created_at: "2026-10-09T12:00:01Z",
        run_id: "run-ai",
        run_status: "succeeded",
        error_message: "",
        metadata: {},
      },
    ],
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => ({
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
                : path.endsWith("/chat/conversations")
                  ? [conversation]
                  : path.includes("/chat/conversations/")
                    ? conversation
                    : [],
    })),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={["/chat/conv"]}>
        <Routes>
          <Route path="/chat/:id" element={<Chat />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const inspect = await screen.findByRole("link", {
    name: "Inspect run Local AI asst-two",
  });
  const copy = screen.getByRole("button", { name: "Copy Local AI asst-two" });
  const articles = screen.getAllByRole("article");
  expect(screen.getByRole("region", { name: "Messages" })).toBeTruthy();
  expect(articles[0].tabIndex).toBe(-1);
  expect(articles[1].tabIndex).toBe(0);
  expect(inspect.tabIndex).toBe(0);
  expect(copy.tabIndex).toBe(0);
  fireEvent.keyDown(articles[1].closest(".chat-messages") as HTMLElement, {
    key: "ArrowUp",
  });
  expect(articles[0].tabIndex).toBe(0);
  expect(articles[1].tabIndex).toBe(-1);
  expect(inspect.tabIndex).toBe(-1);
  fireEvent.keyDown(articles[0].closest(".chat-messages") as HTMLElement, {
    key: "End",
  });
  expect(articles[1].tabIndex).toBe(0);
  expect(inspect.tabIndex).toBe(0);
});

it("moves through conversation history with arrow keys", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => ({
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
                : [
                    {
                      id: "chat-one",
                      title: "Planning",
                      provider: "local-openai-compatible",
                      model: "test-model",
                      system_prompt: "",
                      temperature: 0.7,
                      max_tokens: 2048,
                      updated_at: "2026-10-09T12:00:00Z",
                    },
                    {
                      id: "chat-two",
                      title: "Evening notes",
                      provider: "local-openai-compatible",
                      model: "test-model",
                      system_prompt: "",
                      temperature: 0.7,
                      max_tokens: 2048,
                      updated_at: "2026-10-09T13:00:00Z",
                    },
                  ],
    })),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={["/chat"]}>
        <Routes>
          <Route path="/chat" element={<Chat />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const first = await screen.findByRole("link", {
    name: "Inspect Planning chat-one",
  });
  const second = screen.getByRole("link", {
    name: "Inspect Evening notes chat-two",
  });
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(screen.getByRole("region", { name: "Conversations" })).toBeTruthy();
  fireEvent.keyDown(first.closest(".chat-conversations") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  expect(document.activeElement).toBe(second);
  fireEvent.keyDown(second.closest(".chat-conversations") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
});
