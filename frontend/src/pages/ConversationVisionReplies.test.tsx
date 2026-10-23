import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import Chat from "./Chat";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("shows the Vision answer as one assistant reply with inspectable execution, correct keyboard selection and no unsupported replay", async () => {
  const provider = {
    key: "local-openai-compatible",
    enabled: true,
    builtin: true,
    location: "local",
    default_model: "test-model",
    models: ["test-model"],
    secret_present: false,
  };
  const base = {
    created_at: "2026-10-23T12:00:00Z",
    error_message: "",
    run_status: "succeeded",
  };
  const notice = "Reading image pixels locally with the selected model.";
  const conversation = {
    id: "vision",
    title: "Image question",
    provider: provider.key,
    model: "test-model",
    system_prompt: "",
    temperature: 0.7,
    max_tokens: 2048,
    updated_at: base.created_at,
    execution_mode: "chat",
    active_run: null,
    auto_summary: false,
    summary: null,
    messages: [
      {
        ...base,
        id: "user",
        role: "user",
        content: "What is in this picture?",
        run_id: "root-run",
        metadata: {},
      },
      {
        ...base,
        id: "notice",
        role: "assistant",
        content: notice,
        run_id: "root-run",
        task_status: "succeeded",
        metadata: { orchestration: true },
        steps: [
          {
            id: "root-run",
            capability: "assistant.orchestrate",
            status: "succeeded",
            summary: "",
            error_message: "",
            location: "local",
          },
          {
            id: "vision-run",
            capability: "chat.vision",
            status: "succeeded",
            summary: "",
            error_message: "",
            location: "local",
          },
        ],
        artifacts: [],
      },
      {
        ...base,
        id: "vision-reply",
        role: "assistant",
        content: "A red rectangle.",
        run_id: "vision-run",
        metadata: { vision_model: "local-vision" },
      },
    ],
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => ({
      ok: true,
      json: async () =>
        path.endsWith("/chat/providers")
          ? [provider]
          : path.includes("/chat/providers/")
            ? provider
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
      <MemoryRouter initialEntries={["/chat/vision"]}>
        <Routes>
          <Route path="/chat/:id" element={<Chat />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByText("A red rectangle.");
  const articles = screen.getAllByRole("article");
  expect(articles).toHaveLength(2);
  const inspect = screen.getByRole("link", {
    name: "Inspect run Local AI vision-r",
  });
  expect(inspect.getAttribute("href")).toBe("/runs/vision-run");
  expect(
    screen.queryByRole("button", { name: "Regenerate last response" }),
  ).toBeNull();
  const execution = screen.getByText("Execution details", {
    selector: "summary",
  });
  expect(screen.getByText(notice).closest("details")).toBe(
    execution.closest("details"),
  );
  expect(execution.closest("details")!.open).toBe(false);
  fireEvent.click(execution);
  expect(
    screen
      .getByRole("link", { name: "assistant.orchestrate" })
      .getAttribute("href"),
  ).toBe("/runs/root-run");
  fireEvent.keyDown(articles[0].closest(".chat-messages")!, { key: "Home" });
  expect(inspect.tabIndex).toBe(-1);
  fireEvent.keyDown(articles[0].closest(".chat-messages")!, { key: "End" });
  expect(inspect.tabIndex).toBe(0);
});
