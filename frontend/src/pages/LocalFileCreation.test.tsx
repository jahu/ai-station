import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import AgentDataFiles, { type DataScope } from "./AgentDataFiles";
import ConversationDataControls from "./ConversationDataControls";
import type { ConversationDataScope } from "./useDataInputs";
import { activationBlock } from "./agentActivation";
import AgentDataResult from "./AgentDataResult";
import type { Run } from "../api";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function wrap(element: React.ReactNode) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({ models: [], instances: [] }),
    })),
  );
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>{element}</MemoryRouter>
    </QueryClientProvider>,
  );
}
it("creates from an empty agent scope without upload controls and retains operation when changing fixes", () => {
  const changed = vi.fn();
  function Form() {
    const [value, setValue] = useState<DataScope>({
      input_artifact_ids: [],
      max_repairs: 1,
    });
    return (
      <AgentDataFiles
        value={value}
        disabled={false}
        onChange={(next) => {
          changed(next);
          setValue(next);
        }}
      />
    );
  }
  wrap(<Form />);
  fireEvent.change(screen.getByLabelText("Data operation"), {
    target: { value: "create" },
  });
  expect(screen.getByText("Create files")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Upload data" })).toBeNull();
  fireEvent.change(screen.getByLabelText("Automatic fixes"), {
    target: { value: "2" },
  });
  expect(changed.mock.calls.at(-1)?.[0]).toEqual({
    input_artifact_ids: [],
    max_repairs: 2,
    operation: "create",
  });
});
it("keeps selected files instead of silently switching to creation", () => {
  const changed = vi.fn();
  wrap(
    <AgentDataFiles
      value={{ input_artifact_ids: ["existing"], max_repairs: 1 }}
      disabled={false}
      onChange={changed}
    />,
  );
  const option = screen.getByRole("option", {
    name: "Create files from instructions",
  }) as HTMLOptionElement;
  expect(option.disabled).toBe(true);
  fireEvent.change(screen.getByLabelText("Data operation"), {
    target: { value: "create" },
  });
  expect(changed).not.toHaveBeenCalled();
});
it("keeps public sources explicit while selecting creation in a conversation", () => {
  function Form() {
    const [value, setValue] = useState<ConversationDataScope>({
      input_artifact_ids: [],
      max_repairs: 1,
    });
    return (
      <ConversationDataControls
        value={value}
        disabled={false}
        onChange={setValue}
        onUploading={() => {}}
      />
    );
  }
  wrap(<Form />);
  fireEvent.change(screen.getByLabelText("Data operation"), {
    target: { value: "create" },
  });
  expect(screen.queryByLabelText("Use public sources for analysis")).toBeNull();
  expect(
    screen.getByText(/without reading existing files or visiting websites/),
  ).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Data operation"), {
    target: { value: "analyze" },
  });
  fireEvent.click(screen.getByLabelText("Use public sources for analysis"));
  expect(
    (
      screen.getByRole("option", {
        name: "Create files from instructions",
      }) as HTMLOptionElement
    ).disabled,
  ).toBe(true);
});
it("activates creation only with its saved readiness and no source scope", () => {
  const catalog = [
    {
      name: "python_data",
      description: "Create files",
      operational: true,
      required_permissions: [],
    },
  ];
  const base = {
    enabled: false,
    model: "auto",
    tools: ["python_data"],
    data: {
      input_artifact_ids: [],
      max_repairs: 1,
      operation: "create" as const,
    },
    data_readiness: { ready: true, reason: "Create files from instructions" },
  };
  expect(activationBlock(base, catalog).blocked).toBe(false);
  expect(
    activationBlock(
      { ...base, data: { ...base.data, input_artifact_ids: ["not-empty"] } },
      catalog,
    ).blocked,
  ).toBe(true);
  expect(
    activationBlock(
      { ...base, data_readiness: { ready: false, reason: "Not ready" } },
      catalog,
    ).blocked,
  ).toBe(true);
});
it("labels real created outputs without claiming existing inputs were analyzed", () => {
  const runs = [
    {
      id: "result",
      task_id: "task",
      executor_type: "agent_data_result",
      status: "succeeded",
      parameters: {},
      metadata: {
        data_result: {
          operation: "create",
          answer: "Created the requested table",
          columns: ["Number"],
          rows: [["1"]],
          download_artifact_id: "download",
          script_artifact_id: "script",
          input_artifact_ids: [],
          attempt: 0,
        },
      },
    },
  ] as unknown as Run[];
  wrap(<AgentDataResult runs={runs} />);
  expect(
    screen.getByRole("region", { name: "File creation result" }),
  ).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Created files" })).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "Download CSV" }).getAttribute("href"),
  ).toBe("/api/artifacts/download/file");
});
