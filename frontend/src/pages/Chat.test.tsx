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
  const advanced = screen
    .getByText("Advanced settings")
    .closest("details") as HTMLDetailsElement;
  expect(advanced.open).toBe(false);
  fireEvent.click(screen.getByText("Advanced settings"));
  expect(screen.getByLabelText("Mode local")).toBeTruthy();
  expect(screen.getByLabelText("Conversation title")).toBeTruthy();
  expect(
    screen.getByLabelText("Provider local-openai-compatible"),
  ).toBeTruthy();
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

it("moves through saved transcript attachments without inspecting a Run", async () => {
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
        content: "See these notes",
        created_at: "2026-10-09T12:00:00Z",
        run_id: "run-ai",
        run_status: "succeeded",
        error_message: "",
        metadata: {
          attachments: [
            {
              id: "att-notes-aaaa",
              name: "notes.txt",
              size_bytes: 12,
              kind: "text",
            },
            {
              id: "att-photo-bbbb",
              name: "photo.png",
              size_bytes: 2048,
              kind: "image",
            },
          ],
        },
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
  const first = await screen.findByRole("link", {
    name: "Saved attachment notes.txt att-note",
  });
  const second = screen.getByRole("link", {
    name: "Saved attachment photo.png att-phot",
  });
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(first.getAttribute("href")).toBe("/api/artifacts/att-notes-aaaa/file");
  expect(
    screen.getByText(/There is no inspectable attachment Run/),
  ).toBeTruthy();
  fireEvent.keyDown(
    first.closest(".chat-saved-attachment-list") as HTMLElement,
    { key: "ArrowDown" },
  );
  expect(second.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  expect(document.activeElement).toBe(second);
  fireEvent.keyDown(
    second.closest(".chat-saved-attachment-list") as HTMLElement,
    { key: "Enter" },
  );
  expect(document.activeElement).toBe(second);
  fireEvent.keyDown(
    second.closest(".chat-saved-attachment-list") as HTMLElement,
    { key: "Home" },
  );
  expect(first.tabIndex).toBe(0);
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

it("overrides this turn without sending or rewriting conversation settings", async () => {
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
    ],
  };
  const fetch = vi.fn(async (path: string, options?: RequestInit) => {
    if (options?.method === "POST" || options?.method === "PATCH") {
      throw new Error(`unexpected ${options.method} ${path}`);
    }
    return {
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
    };
  });
  vi.stubGlobal("fetch", fetch);
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
  const auto = await screen.findByLabelText("Turn auto");
  expect(screen.queryByRole("combobox", { name: "Action" })).toBeNull();
  const list = auto.closest(".turn-choice-list") as HTMLElement;
  fireEvent.keyDown(list, { key: "End" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    (
      screen
        .getByLabelText("Turn orchestrator")
        .querySelector("input") as HTMLInputElement
    ).checked,
  ).toBe(true);
  expect(await screen.findByRole("combobox", { name: "Action" })).toBeTruthy();
});

it.each(["image.generate", "image.generate_video"])(
  "keeps optional web research for %s and sends the reviewed query",
  async (action) => {
    const conversation = {
      id: "research",
      title: "Research an image",
      provider: builtin.key,
      provider_name: builtin.name,
      provider_location: "local",
      model: "test-model",
      system_prompt: "",
      temperature: 0.7,
      max_tokens: 2048,
      updated_at: "2026-10-13T12:00:00Z",
      execution_mode: "orchestrator",
      auto_summary: false,
      summary: null,
      active_run: null,
      messages: [],
    };
    const requests: { path: string; body: unknown }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (path: string, init?: RequestInit) => {
        if (init?.method === "POST") {
          requests.push({ path, body: JSON.parse(String(init.body)) });
          return { ok: true, json: async () => ({ id: "queued" }) };
        }
        return {
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
        };
      }),
    );
    render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <MemoryRouter initialEntries={["/chat/research"]}>
          <Routes>
            <Route path="/chat/:id" element={<Chat />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const toggle = await screen.findByRole("switch", {
      name: "Search the web",
    });
    fireEvent.click(toggle);
    fireEvent.change(screen.getByLabelText("Search query"), {
      target: { value: "example.com brand" },
    });
    fireEvent.change(screen.getByLabelText("Action", { exact: true }), {
      target: { value: action },
    });
    expect(
      screen
        .getByRole("switch", { name: "Search the web" })
        .getAttribute("aria-checked"),
    ).toBe("true");
    fireEvent.change(screen.getByLabelText("Message", { exact: true }), {
      target: { value: "Create a promotional image" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await vi.waitFor(() => expect(requests).toHaveLength(1));
    expect(requests[0]).toEqual({
      path: "/api/chat/conversations/research/messages",
      body: expect.objectContaining({
        action,
        web_search: { enabled: true, query: "example.com brand" },
      }),
    });
  },
);
