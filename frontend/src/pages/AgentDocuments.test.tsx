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
import { useState, type ReactNode } from "react";
import { api, type Artifact, type Run } from "../api";
import AgentDocuments from "./AgentDocuments";
import AgentCodeResearch from "./AgentCodeResearch";
import AgentMediaResult from "./AgentMediaResult";
import { AgentLatestReport } from "./AgentLatestReport";
import { activationBlock, localResearchScope } from "./agentActivation";
import { agentSettingsPayload } from "./agentSettings";
import {
  initialDocumentToolMode,
  type DocumentScope,
} from "./document-context";

vi.mock("../api", () => ({ api: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});
function mount(child: ReactNode) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>{child}</MemoryRouter>
    </QueryClientProvider>,
  );
}
function artifact(id: string, name: string, mime = "text/plain", size = 100) {
  return {
    id,
    original_filename: name,
    mime_type: mime,
    size_bytes: size,
    metadata: {},
  } as Artifact;
}
it("keeps a partial upload in one saved selection when the second file fails", async () => {
  const change = vi.fn();
  let calls = 0;
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === "/documents/uploads" && ++calls === 2)
      throw new Error("Invalid second document");
    return artifact("first", "first.txt");
  });
  function Editor() {
    const [value, setValue] = useState<DocumentScope | null>();
    return (
      <AgentDocuments
        value={value}
        disabled={false}
        onChange={(next) => {
          change(next);
          setValue(next);
        }}
      />
    );
  }
  mount(<Editor />);
  fireEvent.change(screen.getByLabelText("Upload agent documents"), {
    target: {
      files: [
        new File(["hello"], "first.txt"),
        new File(["%PDF broken"], "second.pdf"),
      ],
    },
  });
  await screen.findByText("Invalid second document");
  expect(change).toHaveBeenCalledExactlyOnceWith({ artifact_ids: ["first"] });
  expect(screen.getByRole("link", { name: "first.txt" })).toBeTruthy();
  expect(
    vi.mocked(api).mock.calls.every(([path]) => !path.includes("/agents")),
  ).toBe(true);
  fireEvent.click(
    screen.getByRole("button", { name: "Remove document first.txt" }),
  );
  expect(change).toHaveBeenLastCalledWith(null);
});
it("blocks unsupported uploads and ignores drops while edits are locked", async () => {
  const change = vi.fn();
  const { rerender } = mount(
    <AgentDocuments disabled={false} onChange={change} />,
  );
  fireEvent.change(screen.getByLabelText("Upload agent documents"), {
    target: { files: [new File(["binary"], "bad.exe")] },
  });
  await screen.findByText("Choose PDF, UTF-8 text or Markdown documents.");
  expect(api).not.toHaveBeenCalled();
  rerender(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <AgentDocuments disabled onChange={change} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.drop(screen.getByRole("region", { name: "Selected documents" }), {
    dataTransfer: { files: [new File(["hello"], "drop.txt")] },
  });
  expect(change).not.toHaveBeenCalled();
  expect(api).not.toHaveBeenCalled();
});
it("offers stored PDF and text through a separate Library filter, with keyboard selection", async () => {
  vi.mocked(api).mockResolvedValue([
    artifact("pdf", "contract.pdf", "application/pdf"),
    artifact("text", "notes.md", "text/markdown"),
    artifact("data", "sales.csv", "text/csv"),
    artifact("big", "large.txt", "text/plain", 300000),
  ]);
  const change = vi.fn();
  mount(<AgentDocuments disabled={false} onChange={change} />);
  fireEvent.click(
    screen.getByRole("button", { name: "Documents from Library" }),
  );
  const pdf = await screen.findByRole("button", {
    name: "Choose contract.pdf pdf",
  });
  expect(screen.queryByRole("button", { name: /Choose sales/ })).toBeNull();
  expect(screen.queryByRole("button", { name: /Choose large/ })).toBeNull();
  expect(vi.mocked(api).mock.calls[0][0]).toContain("kind=references");
  pdf.focus();
  fireEvent.keyDown(pdf, { key: "ArrowRight" });
  expect(document.activeElement).toBe(
    screen.getByRole("button", { name: "Choose notes.md text" }),
  );
  fireEvent.click(pdf);
  await waitFor(() =>
    expect(
      screen
        .getByRole("button", { name: "Attach file" })
        .hasAttribute("disabled"),
    ).toBe(false),
  );
  fireEvent.click(screen.getByRole("button", { name: "Attach file" }));
  expect(change).toHaveBeenCalledExactlyOnceWith({ artifact_ids: ["pdf"] });
});
it("requires a ready selection for activation and clears its scope when the tool is removed", () => {
  const tool = {
    name: "read_documents",
    description: "",
    operational: true,
    required_permissions: ["filesystem_read"],
  };
  const base = {
    name: "Report",
    enabled: false,
    updated_at: "now",
    model: "local",
    tools: [tool.name],
  };
  expect(activationBlock(base, [tool]).blocked).toBe(true);
  expect(
    activationBlock(
      {
        ...base,
        documents: { artifact_ids: ["doc"] },
        document_readiness: { ready: true, reason: "" },
      },
      [tool],
    ).blocked,
  ).toBe(false);
  expect(
    activationBlock(
      {
        ...base,
        documents: { artifact_ids: ["doc"] },
        document_readiness: { ready: false, reason: "File changed" },
      },
      [tool],
    ).reason,
  ).toBe("File changed");
  expect(
    agentSettingsPayload(
      { ...base, documents: { artifact_ids: ["doc"] } },
      { tools: [] },
    ).documents,
  ).toBeNull();
  expect(localResearchScope(["python_data", "read_documents"])).toBe(true);
  expect(localResearchScope(["coding_cursor", "read_documents"])).toBe(false);
  expect(initialDocumentToolMode(base.tools, null)).toBe("bounded");
  expect(initialDocumentToolMode(["python_data", "read_documents"], null)).toBe(
    "none",
  );
  expect(
    initialDocumentToolMode(base.tools, { artifact_ids: ["doc"] }, "none"),
  ).toBe("none");
});
const observation = {
  artifact_id: "capture",
  captured_at: "2026-10-24T12:00:00Z",
  documents: [
    {
      source_artifact_id: "original",
      text_artifact_id: "text",
      name: "contract.pdf",
      text: "Reviewed document excerpt",
      page_count: 10,
      truncated: true,
      excerpted: true,
    },
  ],
};
function rows() {
  const common = {
    task_id: "task",
    agent_id: "agent",
    project_id: null,
    parent_run_id: "root",
    status: "succeeded",
  };
  return [
    {
      ...common,
      id: "handoff",
      executor_type: "agent_page_coding",
      parameters: { source_run_ids: ["docs", "foreign"] },
    },
    {
      ...common,
      id: "docs",
      executor_type: "agent_tool",
      parameters: { tool: "read_documents" },
      metadata: { observation },
    },
    {
      ...common,
      id: "foreign",
      task_id: "other",
      executor_type: "agent_tool",
      parameters: { tool: "read_documents" },
      metadata: {
        observation: {
          ...observation,
          artifact_id: "foreign",
          documents: [
            { ...observation.documents[0], name: "PRIVATE DOCUMENT" },
          ],
        },
      },
    },
  ] as unknown as Run[];
}
it("shows source, capture and truncation beside local results, excluding another task's documents", () => {
  mount(<AgentCodeResearch runs={rows()} taskId="task" />);
  fireEvent.click(
    screen.getByLabelText("Context for this task").querySelector("summary")!,
  );
  expect(screen.getByText("contract.pdf")).toBeTruthy();
  expect(screen.getByText(/Extraction limit reached/).textContent).toContain(
    "Model received an excerpt",
  );
  expect(
    screen
      .getByRole("link", { name: "Original document" })
      .getAttribute("href"),
  ).toBe("/library/original");
  expect(
    screen
      .getByRole("link", { name: "Full captured text" })
      .getAttribute("href"),
  ).toBe("/library/text");
  expect(
    screen
      .getByRole("link", { name: "Document reading Run" })
      .getAttribute("href"),
  ).toBe("/runs/docs");
  expect(screen.queryByText("PRIVATE DOCUMENT")).toBeNull();
});
it("shows the report's own recorded document context without selecting newer unrelated runs", async () => {
  vi.mocked(api).mockResolvedValue([]);
  mount(
    <AgentLatestReport
      runs={[
        {
          id: "report",
          executor_type: "agent",
          status: "succeeded",
          parameters: {
            tool_context: [{ tool: "read_documents", result: observation }],
          },
          metadata: {},
        } as unknown as Run,
        ...rows(),
      ]}
    />,
  );
  expect(
    screen.getByRole("region", { name: "Captured document sources" }),
  ).toBeTruthy();
  expect(
    screen
      .getByRole("link", { name: "Inspect document capture" })
      .getAttribute("href"),
  ).toBe("/library/capture");
  expect(screen.queryByText("PRIVATE DOCUMENT")).toBeNull();
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith("/artifacts?run_id=report"),
  );
});

it("shows the exact later document search separately from the initial report excerpt", async () => {
  vi.mocked(api).mockResolvedValue([]);
  mount(
    <AgentLatestReport
      runs={[
        {
          id: "report",
          executor_type: "agent",
          status: "succeeded",
          parameters: {},
          metadata: {
            tool_calls: [
              {
                id: "query",
                round: 0,
                tool: "read_documents",
                result: {
                  ...observation,
                  query: "missing phrase",
                  documents: [
                    { ...observation.documents[0], query_found: false },
                  ],
                },
              },
            ],
          },
        } as unknown as Run,
      ]}
    />,
  );
  expect(screen.getByText("Document search: missing phrase")).toBeTruthy();
  expect(screen.getByText("No matching text in this capture.")).toBeTruthy();
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith("/artifacts?run_id=report"),
  );
});
it("keeps the selected document sources next to goal-based media preparation", () => {
  mount(
    <AgentMediaResult
      runs={[
        {
          id: "media",
          task_id: "task",
          executor_type: "agent_media",
          status: "running",
          parameters: {
            definition: { media: { kind: "music" } },
            media_context_snapshot: {
              observations: [{ tool: "read_documents", result: observation }],
            },
          },
        } as unknown as Run,
      ]}
    />,
  );
  expect(
    screen.getByRole("region", { name: "Captured document sources" }),
  ).toBeTruthy();
  expect(
    screen
      .getByRole("link", { name: "Inspect preparation" })
      .getAttribute("href"),
  ).toBe("/runs/media");
});
