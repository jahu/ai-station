import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import CodingSession from "./CodingSessions";

afterEach(() => {
  cleanup();
  sessionStorage.clear();
  vi.unstubAllGlobals();
});
function task(id: string) {
  const external = id === "two";
  return {
    id,
    title: `Task ${id}`,
    project_id: `project-${id}`,
    project_name: `Project ${id}`,
    status: "succeeded",
    active_run_id: null,
    latest_proposal_id: `${id}-source`,
    runs: [
      {
        id: `${id}-source`,
        task_id: id,
        executor_type: external ? "cursor_proposal" : "local_proposal",
        status: "succeeded",
        created_at: "2026-10-15T10:00:00Z",
        parameters: { prompt: `Initial ${id}` },
        metadata: { execution_location: external ? "external" : "local" },
        summary: `Result ${id}`,
      },
    ],
  };
}
function mount(
  onPost: () => Promise<unknown> = async () => ({
    ok: true,
    json: async () => ({ id: "next" }),
  }),
  initial = "one",
) {
  const fetcher = vi.fn(async (path: string, options?: RequestInit) => {
    if (options?.method === "POST") return onPost();
    return {
      ok: true,
      json: async () => task(path.endsWith("/two") ? "two" : "one"),
    };
  });
  vi.stubGlobal("fetch", fetcher);
  const view = render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={[`/coding/${initial}`]}>
        <Link to="/coding/one">One</Link>
        <Link to="/coding/two">Two</Link>
        <Routes>
          <Route path="/coding/:id" element={<CodingSession />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...view, fetcher };
}
const field = () =>
  screen.findByRole("textbox", {
    name: "Follow-up instruction",
  }) as Promise<HTMLTextAreaElement>;
const posts = (fetcher: ReturnType<typeof vi.fn>) =>
  fetcher.mock.calls.filter(
    (call) => (call[1] as RequestInit | undefined)?.method === "POST",
  );

it("keeps task drafts separate while navigating and never restores external consent", async () => {
  const { fetcher } = mount();
  fireEvent.change(await field(), {
    target: { value: "Continue the first task" },
  });
  fireEvent.click(screen.getByRole("link", { name: "Two" }));
  expect((await field()).value).toBe("");
  fireEvent.change(await field(), {
    target: { value: "Continue the second task" },
  });
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("link", { name: "One" }));
  expect((await field()).value).toBe("Continue the first task");
  fireEvent.click(screen.getByRole("link", { name: "Two" }));
  expect((await field()).value).toBe("Continue the second task");
  expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(
    false,
  );
  expect(posts(fetcher)).toHaveLength(0);
});

it("restores after refresh and discards only the current task draft", async () => {
  const first = mount();
  fireEvent.change(await field(), { target: { value: "Keep after reload" } });
  sessionStorage.setItem("ai-station:chat-draft:coding:two", "Another task");
  first.unmount();
  const second = mount();
  expect((await field()).value).toBe("Keep after reload");
  expect(screen.getByText("Unsent draft restored.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Discard draft" }));
  expect((await field()).value).toBe("");
  expect(sessionStorage.getItem("ai-station:chat-draft:coding:two")).toBe(
    "Another task",
  );
  expect(posts(second.fetcher)).toHaveLength(0);
});

it("sends local follow-up with Ctrl+Enter while plain Enter and IME keep editing", async () => {
  const { fetcher } = mount();
  const input = await field();
  fireEvent.change(input, { target: { value: "Add a footer" } });
  fireEvent.keyDown(input, { key: "Enter" });
  fireEvent.keyDown(input, { key: "Enter", ctrlKey: true, isComposing: true });
  expect(posts(fetcher)).toHaveLength(0);
  fireEvent.keyDown(input, { key: "Enter", ctrlKey: true });
  await waitFor(() => expect(posts(fetcher)).toHaveLength(1));
  expect(
    JSON.parse((posts(fetcher)[0][1] as RequestInit).body as string),
  ).toEqual({
    prompt: "Add a footer",
    expected_run_id: "one-source",
    external_ai: false,
  });
  await waitFor(() => expect(input.value).toBe(""));
  expect(sessionStorage.getItem("ai-station:chat-draft:coding:one")).toBeNull();
});

it("Cmd+Enter cannot bypass external sharing consent", async () => {
  const { fetcher } = mount(undefined, "two");
  const input = await field();
  fireEvent.change(input, { target: { value: "Add a footer" } });
  fireEvent.keyDown(input, { key: "Enter", metaKey: true });
  expect(posts(fetcher)).toHaveLength(0);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.keyDown(input, { key: "Enter", metaKey: true });
  await waitFor(() => expect(posts(fetcher)).toHaveLength(1));
  expect(
    JSON.parse((posts(fetcher)[0][1] as RequestInit).body as string)
      .external_ai,
  ).toBe(true);
});

it("preserves a newer draft written while an earlier Send is pending", async () => {
  let finish!: (value: unknown) => void;
  const response = new Promise((resolve) => {
    finish = resolve;
  });
  const { fetcher } = mount(() => response);
  const input = await field();
  fireEvent.change(input, { target: { value: "Submitted instruction" } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => expect(posts(fetcher)).toHaveLength(1));
  fireEvent.change(input, { target: { value: "Next instruction" } });
  finish({ ok: true, json: async () => ({ id: "next" }) });
  await waitFor(() =>
    expect(
      (screen.getByRole("button", { name: "Send" }) as HTMLButtonElement)
        .disabled,
    ).toBe(false),
  );
  expect(input.value).toBe("Next instruction");
  expect(sessionStorage.getItem("ai-station:chat-draft:coding:one")).toBe(
    "Next instruction",
  );
});

it("retains a draft when a Send fails and clips to the Coding API limit", async () => {
  mount(async () => {
    throw new Error("Connection lost");
  });
  const input = await field();
  fireEvent.change(input, { target: { value: "x".repeat(4100) } });
  expect(input.value).toHaveLength(4000);
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  await screen.findByText("Connection lost");
  expect(input.value).toHaveLength(4000);
  expect(
    sessionStorage.getItem("ai-station:chat-draft:coding:one"),
  ).toHaveLength(4000);
});
