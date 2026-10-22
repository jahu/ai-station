import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import AgentDraftForm from "./AgentDraftForm";

function Location() {
  return <output data-testid="location">{useLocation().search}</output>;
}
function mount(initial = "/agents") {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={[initial]}>
        <Routes>
          <Route
            path="/agents"
            element={
              <>
                <AgentDraftForm />
                <Location />
              </>
            }
          />
          <Route path="/agents/:id" element={<h1>Review draft</h1>} />
          <Route path="/runs/:id" element={<h1>Execution details</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
const pending = {
  id: "prepare-1",
  status: "running",
  parameters: {
    instruction: "Summarize local AI news every morning",
    model: "local",
  },
  metadata: {},
};
function fixture(initial = pending, failPost = false) {
  let run = { ...initial };
  const writes: { url: string; body: Record<string, unknown> }[] = [];
  const fetch = vi.fn(async (url: string, options?: RequestInit) => {
    if (options?.method === "POST") {
      writes.push({
        url,
        body: options.body ? JSON.parse(String(options.body)) : {},
      });
      if (url.endsWith("/cancel")) {
        run = { ...run, status: "canceled" };
        return { ok: true, json: async () => run };
      }
      if (failPost)
        return {
          ok: false,
          json: async () => ({
            detail: "The selected local model is unavailable",
          }),
        };
      if (url.endsWith("/agents/draft"))
        return { ok: true, json: async () => ({ id: "quick-1" }) };
      return { ok: true, json: async () => run };
    }
    return {
      ok: true,
      json: async () =>
        url.endsWith("/chat/provider")
          ? { models: ["local"], default_model: "local" }
          : url.endsWith("/llama")
            ? { models: [], instances: [] }
            : url.includes("/agent-drafts/")
              ? run
              : [],
    };
  });
  vi.stubGlobal("fetch", fetch);
  return {
    fetch,
    writes,
    finish: () => {
      run = { ...run, status: "succeeded", metadata: { agent_id: "draft-1" } };
    },
  };
}
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
});

it("queues local preparation, preserves its return URL and opens only the disabled review", async () => {
  const f = fixture();
  mount();
  fireEvent.change(screen.getByLabelText("Instruction"), {
    target: { value: "Summarize local AI news every morning" },
  });
  const send = await screen.findByRole("button", { name: "Create draft" });
  await waitFor(() => expect(send).not.toHaveProperty("disabled", true));
  fireEvent.click(send);
  await screen.findByRole("button", { name: "Stop preparation" });
  expect(screen.getByTestId("location").textContent).toContain(
    "draft_run=prepare-1",
  );
  expect(f.writes).toHaveLength(1);
  expect(f.writes[0].url).toBe("/api/agent-drafts");
  expect(f.writes[0].body.model).toBe("local");
  expect(f.writes[0].body.client_request_id).toMatch(/^[0-9a-f-]{36}$/);
  expect(screen.getByLabelText("Instruction")).toHaveProperty("disabled", true);
  f.finish();
  await screen.findByRole(
    "heading",
    { name: "Review draft" },
    { timeout: 4000 },
  );
  expect(f.writes).toHaveLength(1);
});

it("returns to a persisted preparation after reload without submitting again", async () => {
  const f = fixture();
  mount("/agents?project_id=project-1&draft_run=prepare-1");
  await waitFor(() =>
    expect(screen.getByLabelText("Instruction")).toHaveProperty(
      "value",
      pending.parameters.instruction,
    ),
  );
  expect(
    screen
      .getByRole("link", { name: "Execution details" })
      .getAttribute("href"),
  ).toBe("/runs/prepare-1");
  expect(f.writes).toHaveLength(0);
});

it("stops pending preparation and keeps its instruction for an explicit retry", async () => {
  const f = fixture();
  mount("/agents?draft_run=prepare-1");
  fireEvent.click(
    await screen.findByRole("button", { name: "Stop preparation" }),
  );
  await screen.findByText(
    "Preparation stopped. Your instruction is kept below.",
  );
  expect(screen.getByLabelText("Instruction")).toHaveProperty(
    "value",
    pending.parameters.instruction,
  );
  expect(screen.getByLabelText("Instruction")).toHaveProperty(
    "disabled",
    false,
  );
  expect(f.writes.map((r) => r.url)).toEqual([
    "/api/agent-drafts/prepare-1/cancel",
  ]);
  expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
});

it("shows model failure without publishing, navigating or losing the request", async () => {
  const f = fixture(pending, true);
  mount();
  fireEvent.change(screen.getByLabelText("Instruction"), {
    target: { value: "A useful report" },
  });
  const send = screen.getByRole("button", { name: "Create draft" });
  await waitFor(() => expect(send).not.toHaveProperty("disabled", true));
  fireEvent.click(send);
  await screen.findByText("The selected local model is unavailable");
  expect(screen.getByLabelText("Instruction")).toHaveProperty(
    "value",
    "A useful report",
  );
  const receipt = f.writes[0].body.client_request_id;
  fireEvent.click(send);
  await waitFor(() => expect(f.writes).toHaveLength(2));
  expect(f.writes[1].body.client_request_id).toBe(receipt);
});

it("shows terminal inference failure with a clear retry and no automatic replay", async () => {
  const f = fixture({
    ...pending,
    status: "failed",
    error_message:
      "The local model could not produce a valid agent definition.",
  } as typeof pending);
  mount("/agents?draft_run=prepare-1");
  await screen.findByText(
    "The local model could not produce a valid agent definition.",
  );
  expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
  expect(f.writes).toHaveLength(0);
});

it("keeps the model-free quick draft as an explicit alternative", async () => {
  const f = fixture();
  mount();
  fireEvent.change(screen.getByLabelText("Instruction"), {
    target: { value: "Every morning check my GPU" },
  });
  fireEvent.click(screen.getByText("Without AI"));
  fireEvent.click(screen.getByRole("button", { name: "Create without AI" }));
  await screen.findByRole("heading", { name: "Review draft" });
  expect(f.writes.map((r) => r.url)).toEqual(["/api/agents/draft"]);
});
