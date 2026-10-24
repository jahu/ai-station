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

it.each([
  { mode: "chat", entry: "tool" },
  { mode: "work", entry: "tool" },
  { mode: "chat", entry: "csv" },
  { mode: "work", entry: "csv" },
  { mode: "chat", entry: "xlsx" },
  { mode: "work", entry: "xlsx" },
  { mode: "chat", entry: "json" },
  { mode: "work", entry: "json" },
])(
  "waits for $entry inspection before first Send in $mode and submits only a local data scope",
  async ({ mode, entry }) => {
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
          original_filename:
            entry === "json"
              ? "sales.json"
              : entry === "xlsx"
                ? "sales.xlsx"
                : "sales.csv",
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
    if (entry === "csv" && mode === "work") {
      // Deliberately switching out of project creation must clear that scope.
      fireEvent.change(screen.getByRole("combobox", { name: "Action" }), {
        target: { value: "project.create_code" },
      });
      fireEvent.change(screen.getByRole("combobox", { name: "Action" }), {
        target: { value: "auto" },
      });
    }
    if (entry === "tool")
      fireEvent.change(screen.getByRole("combobox", { name: "Action" }), {
        target: { value: "data.analyze" },
      });
    fireEvent.change(screen.getByRole("textbox", { name: "Message" }), {
      target: { value: "Sum the selected sales" },
    });
    const selected =
      entry === "json"
        ? new File([JSON.stringify({ records: [12, 15] })], "sales.json")
        : entry === "xlsx"
          ? new File([new Uint8Array([0, 255, 80, 75])], "sales.xlsx")
          : new File(["Total\n" + "1\n".repeat(9000)], "sales.csv");
    Object.defineProperty(selected, "arrayBuffer", {
      value: () => {
        throw new Error("Data must never be decoded as an inline attachment");
      },
    });
    fireEvent.change(
      screen.getByLabelText(
        entry === "tool" ? "Upload agent data" : "Attach files",
      ),
      {
        target: { files: [selected] },
      },
    );
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
    expect(writes[0].attachments).toEqual([]);
    expect(JSON.stringify(writes[0])).not.toContain("Total\\n1");
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

it("offers a same-file follow-up only from a verified result and retains the submitted local scope", () => {
  const scope = {
    input_artifact_ids: ["input"],
    max_repairs: 1,
    model: "auto",
    maximum_runtime: 600,
  };
  const runs = [
    {
      id: "result",
      executor_type: "agent_data_result",
      task_id: "task",
      status: "succeeded",
      metadata: {
        data_result: {
          answer: "Total: 27",
          columns: [],
          rows: [],
          download_artifact_id: "csv",
          script_artifact_id: "script",
          attempt: 0,
        },
      },
    },
    {
      id: "origin",
      executor_type: "orchestrator",
      task_id: "task",
      status: "succeeded",
      parameters: { data: scope },
    },
  ] as unknown as Run[];
  const selected = vi.fn();
  const cache = new QueryClient();
  const { rerender } = render(
    <QueryClientProvider client={cache}>
      <MemoryRouter>
        <AssistantResults
          onData={selected}
          result={{ steps: [], data_runs: runs }}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(
    screen.getByRole("button", {
      name: "Ask another question about these files",
    }),
  );
  expect(selected).toHaveBeenCalledExactlyOnceWith(scope);
  expect(scope.input_artifact_ids).toEqual(["input"]);
  rerender(
    <QueryClientProvider client={cache}>
      <MemoryRouter>
        <AssistantResults
          onData={selected}
          result={{ steps: [], data_runs: [runs[1]] }}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(
    screen.queryByRole("button", {
      name: "Ask another question about these files",
    }),
  ).toBeNull();
});

it("keeps partial data uploads and the error visible after the generic attachment control is replaced", async () => {
  let uploads = 0;
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const accepted = vi.fn();
  const artifact = {
    id: "first",
    original_filename: "sales.csv",
    metadata: { data_input: true, data_inspection_run_id: "inspection" },
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      if (path === "/api/data/uploads") {
        if (++uploads === 2)
          return {
            ok: false,
            json: async () => ({ detail: "Second file could not be stored" }),
          };
        return { ok: true, json: async () => artifact };
      }
      const data = path.endsWith("/preferences")
        ? { mode: "chat", model: "plain", provider: provider.key, version: 1 }
        : path.endsWith("/artifacts/first")
          ? artifact
          : path.endsWith("/runs/inspection")
            ? {
                id: "inspection",
                status: "succeeded",
                metadata: { preview_artifact_id: "preview" },
              }
            : path.endsWith("/llama")
              ? { models: [], instances: [] }
              : [];
      expect(init?.method).not.toBe("POST");
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
  const message = await screen.findByRole("textbox", { name: "Message" });
  fireEvent.change(message, { target: { value: "Keep my question" } });
  fireEvent.change(screen.getByLabelText("Attach files"), {
    target: {
      files: [
        new File(["Total\n27"], "sales.csv"),
        new File(["Other\n4"], "other.csv"),
      ],
    },
  });
  await screen.findByText("Second file could not be stored");
  await screen.findByText("sales.csv");
  await screen.findByText("Ready for analysis");
  expect(screen.queryByLabelText("Attach files")).toBeNull();
  expect((message as HTMLTextAreaElement).value).toBe("Keep my question");
  expect(cache.getQueryData(["artifact", "first"])).toEqual(artifact);
  expect(accepted).not.toHaveBeenCalled();
  expect(uploads).toBe(2);
});

it("reviews public sources without files and preserves a newline while entering several URLs", async () => {
  const writes: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        writes.push(JSON.parse(String(init.body)));
        return {
          ok: true,
          json: async () => ({ conversation_id: "public-data" }),
        };
      }
      return {
        ok: true,
        json: async () =>
          path.endsWith("/preferences")
            ? {
                mode: "chat",
                provider: provider.key,
                model: "plain",
                version: 1,
                web_search_enabled: true,
              }
            : path.endsWith("/llama")
              ? { models: [], instances: [] }
              : [],
      };
    }),
  );
  const accepted = vi.fn();
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
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
  fireEvent.change(screen.getByRole("combobox", { name: "Action" }), {
    target: { value: "data.analyze" },
  });
  fireEvent.change(screen.getByRole("textbox", { name: "Message" }), {
    target: { value: "Compare the reviewed public numbers" },
  });
  fireEvent.click(screen.getByLabelText("Use public sources for analysis"));
  const send = screen.getByRole("button", {
    name: "Send message",
  }) as HTMLButtonElement;
  expect(send.disabled).toBe(true);
  const urls = screen.getByLabelText("Public data URLs") as HTMLTextAreaElement;
  fireEvent.change(urls, {
    target: { value: "https://data.example.com/one\n" },
  });
  expect(urls.value).toBe("https://data.example.com/one\n");
  fireEvent.change(urls, {
    target: {
      value: "https://data.example.com/one\nhttps://data.example.com/two",
    },
  });
  fireEvent.change(screen.getByLabelText("Public data search query"), {
    target: { value: "public numbers" },
  });
  fireEvent.click(screen.getByLabelText("Read data search pages"));
  await waitFor(() => expect(send.disabled).toBe(false));
  expect(writes).toHaveLength(0);
  fireEvent.click(send);
  await waitFor(() => expect(accepted).toHaveBeenCalledWith("public-data"));
  expect(writes).toHaveLength(1);
  expect(writes[0].data).toMatchObject({
    input_artifact_ids: [],
    model: "auto",
    research: {
      search_query: "public numbers",
      read_search_pages: true,
      fetch_urls: [
        "https://data.example.com/one",
        "https://data.example.com/two",
      ],
    },
  });
  expect(writes[0].web_search).toMatchObject({ enabled: false });
});

it("offers offline captured-data continuation separately from an explicit public refresh", () => {
  const choose = vi.fn();
  const scope = {
    input_artifact_ids: [],
    model: "auto",
    max_repairs: 1,
    maximum_runtime: 600,
    research: {
      search_query: "",
      fetch_urls: ["https://data.example.com/numbers"],
      read_search_pages: false,
    },
  };
  const root = {
    id: "root",
    task_id: "task",
    executor_type: "orchestrator",
    parameters: { data: scope },
  } as unknown as Run;
  const final = {
    id: "final",
    task_id: "task",
    executor_type: "agent_data_result",
    status: "succeeded",
    metadata: {
      data_result: {
        answer: "Observed total:27",
        columns: ["Total"],
        rows: [["27"]],
        download_artifact_id: "csv",
        script_artifact_id: "script",
        input_artifact_ids: ["capture"],
        attempt: 0,
      },
    },
  } as unknown as Run;
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <AssistantResults
          result={{
            steps: [],
            data_runs: [final, root],
            data_model: "Local",
            task_status: "succeeded",
            artifacts: [],
          }}
          onData={choose}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Ask about these captured data" }),
  );
  expect(choose.mock.calls[0][0].input_artifact_ids).toEqual(["capture"]);
  expect(choose.mock.calls[0][0].research).toBeUndefined();
  fireEvent.click(
    screen.getByRole("button", { name: "Refresh public sources" }),
  );
  expect(choose.mock.calls[1][0]).toEqual(scope);
});
