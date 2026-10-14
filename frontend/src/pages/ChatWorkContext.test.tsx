import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import Chat from "./Chat";

afterEach(() => {
  cleanup();
  sessionStorage.clear();
  vi.unstubAllGlobals();
});
function mount(external = false) {
  const writes: Record<string, unknown>[] = [];
  const context = {
    task_id: "task",
    project_id: "project",
    project_name: "Website",
    title: "Build site",
    expected_run_id: "source",
    executor: external ? "cursor" : "local",
    model: "Coding model",
    external,
    ready: true,
    reason: null,
  };
  const provider = {
    key: "local-openai-compatible",
    enabled: true,
    builtin: true,
    location: "local",
    default_model: "plain",
    models: ["plain"],
    secret_source: "none",
    secret_present: false,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        writes.push(JSON.parse(String(init.body)));
        context.expected_run_id = "next";
        return {
          ok: true,
          json: async () => ({
            conversation_id: "conversation",
            run: { id: "next" },
          }),
        };
      }
      const data = url.endsWith("/chat/conversations/conversation")
        ? {
            id: "conversation",
            title: "Website",
            execution_mode: "work",
            settings_version: 1,
            provider: provider.key,
            model: "plain",
            system_prompt: "",
            temperature: 0.2,
            max_tokens: 2048,
            updated_at: "2026-10-14T12:00:00Z",
            messages: [],
            active_run: null,
            summary: null,
            work_context: context,
          }
        : url.endsWith("/llama")
          ? { models: [], instances: [] }
          : url.endsWith("/chat/providers")
            ? [provider]
            : url.includes("/chat/providers/")
              ? provider
              : url.includes("model-catalog")
                ? { models: [], providers: [] }
                : url.includes("preferences")
                  ? {
                      version: 0,
                      mode: "work",
                      provider: provider.key,
                      model: "plain",
                      send_key: "enter",
                    }
                  : [];
      return { ok: true, json: async () => data };
    }),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={["/chat/conversation"]}>
        <Routes>
          <Route path="/chat/:id" element={<Chat />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return writes;
}
it("continues the visible task and keeps its model and workspace explicit", async () => {
  const writes = mount();
  await screen.findByRole("region", { name: "Current coding task" });
  expect(screen.getByText(/Local AI · Coding model/)).toBeTruthy();
  fireEvent.change(screen.getByRole("textbox", { name: "Message" }), {
    target: { value: "Add tests" },
  });
  fireEvent.click(screen.getByRole("button", { name: /^Send$/ }));
  await vi.waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0].continuation).toEqual({
    task_id: "task",
    expected_run_id: "source",
    external_ai: false,
  });
});
it("requires new external consent for the selected source and next prompt", async () => {
  const writes = mount(true);
  await screen.findByRole("region", { name: "Current coding task" });
  fireEvent.change(screen.getByRole("textbox", { name: "Message" }), {
    target: { value: "Add tests" },
  });
  expect(
    (screen.getByRole("button", { name: /^Send$/ }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  fireEvent.click(
    screen.getByRole("checkbox", {
      name: /Share this prompt and relevant source with cursor/,
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: /^Send$/ }));
  await vi.waitFor(() => expect(writes).toHaveLength(1));
  expect((writes[0].continuation as { external_ai: boolean }).external_ai).toBe(
    true,
  );
  await vi.waitFor(() =>
    expect(
      (
        screen.getByRole("checkbox", {
          name: /Share this prompt/,
        }) as HTMLInputElement
      ).checked,
    ).toBe(false),
  );
});
it("lets the user leave coding context or switch to Chat without losing the prompt", async () => {
  const writes = mount();
  await screen.findByRole("region", { name: "Current coding task" });
  const field = screen.getByRole("textbox", { name: "Message" });
  fireEvent.change(field, { target: { value: "Explain the architecture" } });
  fireEvent.click(screen.getByRole("button", { name: "Use general Work" }));
  expect((field as HTMLTextAreaElement).value).toBe("Explain the architecture");
  expect(sessionStorage.getItem("ai-station:general-work:conversation")).toBe(
    "task",
  );
  fireEvent.click(screen.getByRole("button", { name: /^Chat$/ }));
  expect(
    screen.queryByRole("region", { name: "Current coding task" }),
  ).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /^Send$/ }));
  await vi.waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0].execution_mode).toBe("chat");
  expect(writes[0].continuation).toBeUndefined();
});
