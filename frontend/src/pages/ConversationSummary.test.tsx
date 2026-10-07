import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import ConversationSummary, { type Summary } from "./ConversationSummary";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function mount(summary: Summary | null = null, busy = false) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <ConversationSummary
          conversationId="conversation"
          summary={summary}
          busy={busy}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByText(/Conversation memory/));
}
it("queues summary only on request and exposes failure", async () => {
  const fetch = vi.fn(async () => ({
    ok: false,
    json: async () => ({ detail: "More history is needed" }),
  }));
  vi.stubGlobal("fetch", fetch);
  mount();
  expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Update summary" }));
  await screen.findByText("More history is needed");
  expect(fetch).toHaveBeenCalledWith(
    "/api/chat/conversations/conversation/summarize",
    { method: "POST" },
  );
});
it("makes disabled memory and its provenance explicit while blocking concurrent work", () => {
  mount(
    {
      id: "summary",
      run_id: "run",
      memory_id: "memory",
      enabled: false,
      content: "",
      source_message_ids: ["message"],
      previous_summary_id: null,
      created_at: "2026-09-26T00:00:00Z",
    },
    true,
  );
  expect(
    screen.getByText(/Summary memory is disabled or deleted/),
  ).toBeTruthy();
  expect(
    screen
      .getByRole("link", { name: "Edit or disable memory" })
      .getAttribute("href"),
  ).toBe("/memory/memory");
  expect(
    screen
      .getByRole("link", { name: "Inspect summary Run and sources" })
      .getAttribute("href"),
  ).toBe("/runs/run");
  expect(
    (
      screen.getByRole("button", {
        name: "Update summary",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
});

it("saves automatic memory only after an explicit user selection", async () => {
  const fetch = vi.fn(async () => ({
    ok: true,
    json: async () => ({ auto_summary: true }),
  }));
  vi.stubGlobal("fetch", fetch);
  mount();
  const option = screen.getByRole("checkbox", {
    name: "Automatically maintain conversation memory",
  });
  expect((option as HTMLInputElement).checked).toBe(false);
  expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(option);
  await vi.waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/chat/conversations/conversation/context",
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ auto_summary: true }),
      },
    ),
  );
});
