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
import { AssistantResults } from "./AssistantActions";
import type { ChatProviderInfo } from "./ChatProviders";
import type { Run } from "../api";

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

it.each(["chat", "work"])(
  "waits for file inspection before first Send in %s and submits an isolated local scope",
  async (mode) => {
    let inspected = false;
    const writes: Record<string, unknown>[] = [];
    const cache = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const accepted = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (path: string, init?: RequestInit) => {
        const artifact = {
          id: "input",
          original_filename: "sales.csv",
          metadata: { data_input: true, data_inspection_run_id: "inspection" },
        };
        if (path === "/api/data/uploads")
          return { ok: true, json: async () => artifact };
        if (init?.method === "POST") {
          writes.push(JSON.parse(String(init.body)));
          return { ok: true, json: async () => ({ conversation_id: "saved" }) };
        }
        const data = path.endsWith("/preferences")
          ? { mode, provider: provider.key, model: "plain", version: 1 }
          : path.endsWith("/artifacts/input")
            ? artifact
            : path.endsWith("/runs/inspection")
              ? {
                  id: "inspection",
                  status: inspected ? "succeeded" : "running",
                  metadata: inspected ? { preview_artifact_id: "preview" } : {},
                }
              : path.endsWith("/llama")
                ? {
                    models: [
                      { name: "Local 27B", model_key: "llamacpp:local" },
                    ],
                    instances: [],
                  }
                : [];
        return { ok: true, json: async () => data };
      }),
    );
    render(
      <QueryClientProvider client={cache}>
        <MemoryRouter>
          <NewChat
            providers={[provider]}
            provider={provider}
            onProviderChange={() => {}}
            onAccepted={accepted}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await screen.findByRole("textbox", { name: "Message" });
    if (mode === "work")
      fireEvent.click(screen.getByRole("button", { name: "Work" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Action" }), {
      target: { value: "data.analyze" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Message" }), {
      target: { value: "Sum the selected sales" },
    });
    fireEvent.change(screen.getByLabelText("Upload agent data"), {
      target: { files: [new File(["Total\n27"], "sales.csv")] },
    });
    await screen.findByText("Inspecting file…");
    expect(
      (
        screen.getByRole("button", {
          name: "Send message",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(screen.queryByText("Add images")).toBeNull();
    expect(screen.queryByText("Attach text or PDF")).toBeNull();
    inspected = true;
    await cache.invalidateQueries({ queryKey: ["run", "inspection"] });
    await screen.findByText("Ready for analysis");
    await waitFor(() =>
      expect(
        (
          screen.getByRole("button", {
            name: "Send message",
          }) as HTMLButtonElement
        ).disabled,
      ).toBe(false),
    );
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(accepted).toHaveBeenCalledWith("saved"));
    expect(writes).toHaveLength(1);
    expect(writes[0]).toMatchObject({
      action: "data.analyze",
      data: {
        input_artifact_ids: ["input"],
        model: "auto",
        maximum_runtime: 600,
        max_repairs: 1,
      },
      content: "Sum the selected sales",
      web_search: { enabled: false },
    });
    expect(writes[0]).not.toHaveProperty("project_defaults");
    expect(writes[0]).not.toHaveProperty("continuation");
  },
);

it("shows the verified data table and download before optional execution internals", () => {
  const run = {
    id: "result",
    task_id: "task",
    executor_type: "agent_data_result",
    status: "succeeded",
    metadata: {
      data_result: {
        answer: "Total: 27",
        columns: ["Total"],
        rows: [["27"]],
        download_artifact_id: "csv",
        script_artifact_id: "script",
        input_artifact_ids: ["input"],
        attempt: 1,
      },
    },
  } as unknown as Run;
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <AssistantResults
          result={{
            steps: [
              {
                id: "result",
                capability: "agent.data.result",
                status: "succeeded",
                location: "local",
                summary: "",
                error_message: "",
              },
            ],
            data_runs: [run],
            data_model: "Local 27B",
            task_status: "succeeded",
            artifacts: [],
          }}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(screen.getByText("Total: 27")).toBeTruthy();
  expect(screen.getByRole("table", { name: "Analysis results" })).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "Download CSV" }).getAttribute("href"),
  ).toBe("/api/artifacts/csv/file");
  expect(screen.getByText(/LOCAL · Local 27B/)).toBeTruthy();
  expect(screen.getByText(/Code corrected after 1 attempt/)).toBeTruthy();
  expect(
    screen
      .getByText("Execution details", { selector: "summary" })
      .parentElement?.hasAttribute("open"),
  ).toBe(false);
});
