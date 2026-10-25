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

it.each([
  { mode: "chat", enabled: true },
  { mode: "work", enabled: true },
  { mode: "work", enabled: false },
] as const)(
  "sends the first $mode prompt with the saved Web preference ($enabled)",
  async ({ mode, enabled }) => {
    const writes: { path: string; body: Record<string, unknown> }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (path: string, init?: RequestInit) => {
        if (init?.method === "POST") {
          writes.push({ path, body: JSON.parse(String(init.body)) });
          return { ok: true, json: async () => ({ conversation_id: "new" }) };
        }
        return {
          ok: true,
          json: async () =>
            path.endsWith("/chat/providers")
              ? [builtin]
              : path.includes("/chat/providers/")
                ? builtin
                : path.endsWith("/preferences")
                  ? {
                      version: 0,
                      mode,
                      web_search_enabled: enabled,
                      provider: builtin.key,
                      model: "",
                      send_key: "enter",
                    }
                  : path.endsWith("/llama")
                    ? { models: [], instances: [] }
                    : path.endsWith("/hardware")
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
        <MemoryRouter initialEntries={["/chat"]}>
          <Routes>
            <Route path="/chat" element={<Chat />} />
            <Route path="/chat/new" element={<h1>Created chat</h1>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const message = await screen.findByRole("textbox", { name: "Message" });
    expect(
      screen.queryByRole("button", { name: "Create conversation" }),
    ).toBeNull();
    expect(writes).toHaveLength(0);
    fireEvent.change(message, { target: { value: "Explain this clearly" } });
    await vi.waitFor(() =>
      expect(
        (
          screen.getByRole("button", {
            name: "Send message",
          }) as HTMLButtonElement
        ).disabled,
      ).toBe(false),
    );
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await screen.findByRole("heading", { name: "Created chat" });
    expect(writes).toHaveLength(1);
    expect(writes[0]).toEqual({
      path: "/api/chat/turns",
      body: expect.objectContaining({
        content: "Explain this clearly",
        web_search: { enabled, query: "" },
        execution_mode: mode,
        client_request_id: expect.any(String),
        selection: {
          provider: builtin.key,
          model: "test-model",
          execution_mode: mode,
        },
      }),
    });
  },
);

it.each([undefined, 1, 2, 3, 4, 5, 6])(
  "moves through messages and identifies the resolved input source (%s)",
  async (inputCount) => {
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
          metadata: {
            images:
              (inputCount ?? 0) >= 3
                ? []
                : [{ id: "source-image", name: "landscape.png" }],
            conversation_reference: {
              use_result_file: inputCount === 6,
              source_kind:
                (inputCount ?? 0) >= 4
                  ? "agent_data_inputs"
                  : inputCount === 3
                    ? "analyzed_data"
                    : inputCount
                      ? "inspected_input"
                      : undefined,
              filenames: (inputCount ?? 0) >= 3 ? ["sales.csv"] : undefined,
              captured_sources:
                inputCount === 5
                  ? [
                      {
                        artifact_id: "source-data",
                        captured_at: "2026-10-09T12:00:00Z",
                      },
                    ]
                  : undefined,
              artifact_ids:
                inputCount === 2
                  ? ["source-image", "second-image"]
                  : ["source-image"],
              artifact_id: "source-image",
              message_id: "earlier-message",
              run_id: "source-run",
            },
          },
        },
        {
          id: "asst-two",
          role: "assistant",
          content: "Hi there",
          created_at: "2026-10-09T12:00:01Z",
          run_id: "run-ai",
          run_status: "succeeded",
          error_message: "",
          metadata: {
            transcript_sources: [
              {
                source_message_id: "transcript-message",
                run_id: "transcript-run",
                artifact_id: "transcript-text",
                available: true,
                truncated: true,
                included_characters: 100,
                total_characters: 900,
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
    const inspect = await screen.findByRole("link", {
      name: "Inspect run Local AI asst-two",
    });
    expect(
      screen.getByText(
        inputCount === 6
          ? /Using the result file/
          : inputCount === 5
            ? /Using the agent’s captured data/
            : inputCount === 4
              ? /Using the agent’s input files/
              : inputCount === 3
                ? /Using the analyzed input files · sales.csv/
                : inputCount
                  ? inputCount === 2
                    ? /Using the inspected images/
                    : /Using the inspected image ·/
                  : /Using the previous image result/,
      ),
    ).toBeTruthy();
    expect(screen.getByText(/Using a stored transcript/)).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "Inspect transcript source transcri" })
        .getAttribute("href"),
    ).toBe("/runs/transcript-run");
    expect(
      screen
        .getByRole("link", {
          name: `Inspect referenced ${(inputCount ?? 0) >= 3 ? "data" : "image"} user-one`,
        })
        .getAttribute("href"),
    ).toBe("/runs/source-run");
    if ((inputCount ?? 0) >= 3)
      expect(screen.queryByAltText("Reference 1: landscape.png")).toBeNull();
    else expect(screen.getByAltText("Reference 1: landscape.png")).toBeTruthy();
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
  },
);

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
  const work = await screen.findByRole("button", { name: "Work" });
  const action = screen.getByRole("combobox", { name: "Action" });
  expect(action.querySelector('option[value="coding.local"]')).toBeNull();
  fireEvent.click(work);
  expect(work.getAttribute("aria-pressed")).toBe("true");
  expect(
    screen.queryByText(/New projects include public package preparation/),
  ).toBeNull();
  expect(action.querySelector('option[value="coding.local"]')).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Chat" }));
  expect(action.querySelector('option[value="coding.local"]')).toBeNull();
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
    expect(toggle.getAttribute("aria-checked")).toBe("true");
    await vi.waitFor(() =>
      expect(
        screen
          .getByRole("button", { name: "Search options" })
          .hasAttribute("disabled"),
      ).toBe(false),
    );
    fireEvent.click(screen.getByRole("button", { name: "Search options" }));
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
    await vi.waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Send" }).hasAttribute("disabled"),
      ).toBe(false),
    );
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await vi.waitFor(() => expect(requests).toHaveLength(1));
    expect(requests[0]).toEqual({
      path: "/api/chat/turns",
      body: expect.objectContaining({
        action,
        web_search: { enabled: true, query: "example.com brand" },
      }),
    });
  },
);

it("continues coding a created project with local scope without starting work on click", async () => {
  const project = {
    id: "project-new",
    name: "Weather Station",
    updated_at: "2026-10-14T07:00:00Z",
  };
  const conversation = {
    id: "project-chat",
    title: "Build Weather",
    provider: builtin.key,
    provider_location: "local",
    model: "test-model",
    system_prompt: "",
    temperature: 0.7,
    max_tokens: 2048,
    updated_at: project.updated_at,
    execution_mode: "local",
    active_run: null,
    messages: [
      {
        id: "project-result",
        role: "assistant",
        content: "Project ready",
        created_at: project.updated_at,
        run_id: "setup",
        run_status: "succeeded",
        error_message: "",
        metadata: { orchestration: true },
        steps: [],
        created_projects: [project],
        task_status: "succeeded",
      },
    ],
  };
  const writes: { path: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        writes.push({ path, body: JSON.parse(String(init.body)) });
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
                  : path.startsWith("/api/projects")
                    ? [project]
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
      <MemoryRouter initialEntries={["/chat/project-chat"]}>
        <Routes>
          <Route path="/chat/:id" element={<Chat />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Continue here with Local AI" }),
  );
  expect(writes).toHaveLength(0);
  const selectedProject = await screen.findByRole("radio", {
    name: /Weather Station/,
  });
  expect((selectedProject as HTMLInputElement).checked).toBe(true);
  expect(
    (screen.getByLabelText("Action", { exact: true }) as HTMLSelectElement)
      .value,
  ).toBe("coding.local");
  fireEvent.change(screen.getByLabelText("Message", { exact: true }), {
    target: { value: "Build a weather page" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  await vi.waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0].body).toEqual(
    expect.objectContaining({
      action: "coding.local",
      execution_mode: "work",
      coding: expect.objectContaining({
        project_id: project.id,
        expected_updated_at: project.updated_at,
        files: [],
        external_ai: false,
        explore: true,
      }),
    }),
  );
});

it("retries an uncertain first Send with the same request identity and preserved draft", async () => {
  const posted: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        posted.push(JSON.parse(String(init.body)));
        if (posted.length === 1) throw new Error("Response lost");
        return { ok: true, json: async () => ({ conversation_id: "resumed" }) };
      }
      return {
        ok: true,
        json: async () =>
          path.endsWith("/chat/providers")
            ? [builtin]
            : path.includes("/chat/providers/")
              ? builtin
              : path.endsWith("/preferences")
                ? {
                    version: 0,
                    mode: "chat",
                    provider: builtin.key,
                    model: "",
                    send_key: "enter",
                  }
                : path.endsWith("/llama")
                  ? { models: [], instances: [] }
                  : path.endsWith("/hardware")
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
      <MemoryRouter initialEntries={["/chat"]}>
        <Routes>
          <Route path="/chat" element={<Chat />} />
          <Route path="/chat/resumed" element={<h1>Resumed conversation</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const message = await screen.findByRole("textbox", { name: "Message" });
  fireEvent.change(message, { target: { value: "Keep this instruction" } });
  const send = screen.getByRole("button", { name: "Send message" });
  await vi.waitFor(() =>
    expect((send as HTMLButtonElement).disabled).toBe(false),
  );
  fireEvent.click(send);
  await screen.findByText("Response lost");
  expect((message as HTMLTextAreaElement).value).toBe("Keep this instruction");
  fireEvent.click(send);
  await screen.findByRole("heading", { name: "Resumed conversation" });
  expect(posted).toHaveLength(2);
  expect(posted[0].client_request_id).toBe(posted[1].client_request_id);
});

it.each(["wan_video", "project_setup", "orchestrator", "local_chat"])(
  "stops the complete conversation task during %s without requiring Work context",
  async (executor) => {
    vi.stubGlobal(
      "EventSource",
      class {
        addEventListener() {}
        close() {}
      },
    );
    const job = {
      task_id: "film-task",
      revision: 1,
      kind: "video",
      mode: "continuous",
      status: "generating",
      duration_seconds: 30,
      total_segments: 12,
      completed_segments: 2,
      final_artifact_id: null,
      active_run_ids: ["segment"],
      resume_allowed: false,
      error_message: "",
    };
    const detail = {
      id: "film-chat",
      title: "A film",
      provider: builtin.key,
      provider_location: "local",
      model: "test-model",
      system_prompt: "",
      temperature: 0.7,
      max_tokens: 2048,
      updated_at: "2026-10-14T07:00:00Z",
      execution_mode: "work",
      active_run: {
        id: "segment",
        task_id: "film-task",
        status: "running",
        executor_type: executor,
        parameters: executor === "wan_video" ? { internal_media: true } : {},
      },
      messages: [
        {
          id: "answer",
          role: "assistant",
          content: "Rendering",
          created_at: "2026-10-14T07:00:00Z",
          run_id: "planner",
          run_status: "succeeded",
          error_message: "",
          metadata: { orchestration: true },
          media_job: job,
          steps: [],
          task_status: "generating",
        },
      ],
    };
    const writes: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (init?.method === "POST") writes.push(url);
        return {
          ok: true,
          json: async () =>
            url.includes("/media/jobs/")
              ? job
              : url.endsWith("/chat/providers")
                ? [builtin]
                : url.includes("/chat/providers/")
                  ? builtin
                  : url.endsWith("/hardware")
                    ? { gpus: [] }
                    : url.endsWith("/llama")
                      ? { models: [], instances: [] }
                      : url.endsWith("/chat/conversations")
                        ? [detail]
                        : url.includes("/chat/conversations/")
                          ? detail
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
        <MemoryRouter initialEntries={["/chat/film-chat"]}>
          <Routes>
            <Route path="/chat/:id" element={<Chat />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await screen.findByText("2 of 12 segments complete");
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    await vi.waitFor(() =>
      expect(writes).toEqual([
        "/api/chat/conversations/film-chat/tasks/film-task/cancel",
      ]),
    );
  },
);

it("keeps project automation out of a Chat follow-up", async () => {
  const writes: Record<string, unknown>[] = [];
  const conversation = {
    id: "plain",
    title: "Plain chat",
    provider: builtin.key,
    model: "test-model",
    execution_mode: "chat",
    system_prompt: "",
    temperature: 0.7,
    max_tokens: 300,
    settings_version: 1,
    messages: [],
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        writes.push(JSON.parse(String(init.body)));
        return { ok: true, json: async () => ({ conversation_id: "plain" }) };
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
      <MemoryRouter initialEntries={["/chat/plain"]}>
        <Routes>
          <Route path="/chat/:id" element={<Chat />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.change(await screen.findByRole("textbox", { name: "Message" }), {
    target: { value: "A normal follow-up" },
  });
  await vi.waitFor(() =>
    expect(
      (screen.getByRole("button", { name: "Send" }) as HTMLButtonElement)
        .disabled,
    ).toBe(false),
  );
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  await vi.waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0].execution_mode).toBe("chat");
  expect(writes[0].project_defaults).toBeUndefined();
  expect(
    screen.queryByText(/New projects include public package preparation/),
  ).toBeNull();
});
