import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import AnalysisAgentDialog from "./AnalysisAgentDialog";
import { AssistantResults } from "./AssistantActions";
import type { Run } from "../api";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  sessionStorage.clear();
});
const source = {
  id: "older-analysis",
  goal: "Compare the original sales",
  liveSources: true,
};
function dialog(onCreated = vi.fn(), onClose = vi.fn()) {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <AnalysisAgentDialog
        source={source}
        conversationId="conversation"
        settingsVersion={4}
        providerVersion="version"
        onCreated={onCreated}
        onClose={onClose}
      />
    </QueryClientProvider>,
  );
  return { onCreated, onClose };
}
it("previews the selected source and creates only a disabled Work draft after explicit submission", async () => {
  const writes: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_path: string, init?: RequestInit) => {
      writes.push(JSON.parse(String(init?.body)));
      return { ok: true, json: async () => ({}) };
    }),
  );
  const { onCreated } = dialog();
  expect(
    screen.getByRole("dialog", { name: "Create an agent from this analysis" }),
  ).toBeTruthy();
  expect(screen.getByText(source.goal)).toBeTruthy();
  expect(screen.getByText(/public sources again/)).toBeTruthy();
  expect(writes).toHaveLength(0);
  fireEvent.change(
    screen.getByRole("textbox", { name: "When should it run?" }),
    { target: { value: "Every weekday at 08:30." } },
  );
  fireEvent.click(screen.getByRole("button", { name: "Prepare draft" }));
  await vi.waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
  expect(writes).toHaveLength(1);
  expect(writes[0]).toEqual(
    expect.objectContaining({
      analysis_agent_source_run_id: source.id,
      conversation_id: "conversation",
      expected_settings_version: 4,
      expected_provider_version: "version",
      execution_mode: "assistant",
      action: "agent.create",
      web_search: { enabled: false, query: "" },
      content:
        "Create an agent that repeats this analysis. Every weekday at 08:30.",
      client_request_id: expect.any(String),
    }),
  );
  expect(writes[0]).not.toHaveProperty("data");
  expect(writes[0]).not.toHaveProperty("project_defaults");
});
it("retries an uncertain response with the same receipt and retains entered instructions", async () => {
  const writes: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_path: string, init?: RequestInit) => {
      writes.push(JSON.parse(String(init?.body)));
      if (writes.length === 1) throw new Error("Connection interrupted");
      return { ok: true, json: async () => ({}) };
    }),
  );
  const { onCreated } = dialog();
  fireEvent.click(screen.getByRole("button", { name: "Prepare draft" }));
  await screen.findByRole("alert");
  expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe(
    "Every morning at 09:00.",
  );
  fireEvent.click(screen.getByRole("button", { name: "Prepare draft" }));
  await vi.waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
  expect(writes).toHaveLength(2);
  expect(writes[0]).toEqual(writes[1]);
});
it("cancel creates no request", () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  const { onClose } = dialog();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(onClose).toHaveBeenCalledOnce();
  expect(fetch).not.toHaveBeenCalled();
});
it("offers the exact completed source and hides the action on incomplete results", () => {
  const selected = vi.fn();
  const result = {
    task_status: "succeeded",
    steps: [],
    data_runs: [
      {
        id: "older-analysis",
        executor_type: "orchestrator",
        status: "succeeded",
        parameters: {
          content: source.goal,
          data: {
            input_artifact_ids: [],
            research: { fetch_urls: ["https://example.com/"] },
          },
        },
      },
      {
        id: "result",
        executor_type: "agent_data_result",
        status: "succeeded",
        metadata: { data_result: { answer: "Done", columns: [], rows: [] } },
      },
    ] as unknown as Run[],
  };
  const ui = render(
    <MemoryRouter>
      <AssistantResults result={result} onRepeatAnalysis={selected} />
    </MemoryRouter>,
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Create an agent from this analysis" }),
  );
  expect(selected).toHaveBeenCalledWith(source);
  ui.rerender(
    <MemoryRouter>
      <AssistantResults
        result={{ ...result, task_status: "running" }}
        onRepeatAnalysis={selected}
      />
    </MemoryRouter>,
  );
  expect(
    screen.queryByRole("button", {
      name: "Create an agent from this analysis",
    }),
  ).toBeNull();
});
