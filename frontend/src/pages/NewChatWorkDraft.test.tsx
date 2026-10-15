import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import NewChat from "./NewChat";
import type { ChatProviderInfo } from "./ChatProviders";

const provider = {
  key: "local-openai-compatible",
  enabled: true,
  builtin: true,
  location: "local",
  default_model: "plain",
  models: ["plain"],
  secret_source: "none",
  secret_present: false,
} as ChatProviderInfo;
afterEach(() => {
  cleanup();
  sessionStorage.clear();
  vi.unstubAllGlobals();
});
function mount(external = false, source = "source") {
  const writes: Record<string, unknown>[] = [];
  const accepted = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        writes.push(JSON.parse(String(init.body)));
        return { ok: true, json: async () => ({ conversation_id: "saved" }) };
      }
      const data = path.includes("/work-context")
        ? {
            task_id: "task",
            project_name: "Website",
            title: "Build a site",
            expected_run_id: source,
            executor: external ? "cursor" : "local",
            model: external ? "auto" : "Coding model",
            external,
            ready: true,
            reason: null,
          }
        : path.includes("/preferences")
          ? {
              version: 1,
              mode: "chat",
              provider: provider.key,
              model: "plain",
              send_key: "enter",
            }
          : path.includes("model-catalog")
            ? { models: [], providers: [] }
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
      <MemoryRouter initialEntries={["/chat?work_task=task&work_run=source"]}>
        <NewChat
          providers={[provider]}
          provider={provider}
          onProviderChange={() => {}}
          onAccepted={accepted}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { writes, accepted };
}

it("opens a scoped Work draft without mutation and first Send keeps the selected task/model", async () => {
  const state = mount();
  await screen.findByText("Same branch and workspace", { exact: false });
  expect(state.writes).toEqual([]);
  expect(screen.queryByText("Attach files & choose tools")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Work" }));
  expect(
    screen.getByRole("region", { name: "Selected coding task" }),
  ).toBeTruthy();
  fireEvent.change(screen.getByRole("textbox", { name: "Message" }), {
    target: { value: "Add the next feature" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
  await waitFor(() => expect(state.accepted).toHaveBeenCalledWith("saved"));
  expect(state.writes).toHaveLength(1);
  expect(state.writes[0]).toMatchObject({
    selection: {
      execution_mode: "work",
      provider: provider.key,
      model: "Coding model",
      title: "Build a site",
    },
    continuation: {
      task_id: "task",
      expected_run_id: "source",
      external_ai: false,
    },
  });
  expect(state.writes[0]).not.toHaveProperty("reasoning");
});

it("requires new explicit sharing consent for a Cursor Work draft", async () => {
  const state = mount(true);
  await screen.findByText("Same branch and workspace", { exact: false });
  fireEvent.change(screen.getByRole("textbox", { name: "Message" }), {
    target: { value: "Add a form" },
  });
  expect(
    (screen.getByRole("button", { name: "Send message" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  fireEvent.click(screen.getByRole("checkbox", { name: /Share this prompt/ }));
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
  await waitFor(() => expect(state.writes).toHaveLength(1));
  expect(state.writes[0]).toMatchObject({
    continuation: {
      task_id: "task",
      expected_run_id: "source",
      external_ai: true,
    },
  });
});

it("General Work clears the coding scope while preserving the unsent prompt", async () => {
  const state = mount();
  await screen.findByText("Same branch and workspace", { exact: false });
  const field = screen.getByRole("textbox", { name: "Message" });
  fireEvent.change(field, { target: { value: "Explain this architecture" } });
  fireEvent.click(screen.getByRole("button", { name: "General Work" }));
  expect((field as HTMLTextAreaElement).value).toBe(
    "Explain this architecture",
  );
  expect(state.writes).toEqual([]);
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
  await waitFor(() => expect(state.writes).toHaveLength(1));
  expect(state.writes[0]).not.toHaveProperty("continuation");
});

it("does not silently advance a pinned source after the task changes", async () => {
  const state = mount(false, "new-source");
  await screen.findByText(/The coding task changed since this draft opened/);
  fireEvent.change(screen.getByRole("textbox", { name: "Message" }), {
    target: { value: "Add a form" },
  });
  expect(
    (screen.getByRole("button", { name: "Send message" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  expect(state.writes).toEqual([]);
});
