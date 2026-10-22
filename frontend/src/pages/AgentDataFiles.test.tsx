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
import { api } from "../api";
import AgentDataFiles from "./AgentDataFiles";
vi.mock("../api", () => ({ api: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});
it("uploads a data file through the normal inspection endpoint and freezes only its id", async () => {
  vi.mocked(api).mockResolvedValue({
    id: "input-id",
    original_filename: "sales.csv",
    metadata: { data_input: true },
  });
  const change = vi.fn();
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <AgentDataFiles disabled={false} onChange={change} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.change(screen.getByLabelText("Upload agent data"), {
    target: {
      files: [new File(["Total\n27"], "sales.csv", { type: "text/csv" })],
    },
  });
  await waitFor(() =>
    expect(change).toHaveBeenCalledWith({
      input_artifact_ids: ["input-id"],
      max_repairs: 1,
    }),
  );
  expect(vi.mocked(api).mock.calls[0][0]).toBe("/data/uploads");
  expect(screen.queryByText(/Enabled/)).toBeNull();
});

it("keeps successfully uploaded files selected when a later upload fails", async () => {
  let uploads = 0;
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === "/data/uploads" && ++uploads === 2)
      throw new Error("Invalid second file");
    return {
      id: "first-file",
      original_filename: "first.csv",
      metadata: { data_input: true },
    };
  });
  const change = vi.fn();
  const { useState } = await import("react");
  function Editor() {
    const [value, setValue] = useState<{
      input_artifact_ids: string[];
      max_repairs: number;
    }>();
    return (
      <AgentDataFiles
        value={value}
        disabled={false}
        onChange={(next) => {
          change(next);
          setValue(next);
        }}
      />
    );
  }
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <Editor />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.change(screen.getByLabelText("Upload agent data"), {
    target: {
      files: [
        new File(["Total\n27"], "first.csv"),
        new File(["broken"], "second.xlsx"),
      ],
    },
  });
  await screen.findByText("Invalid second file");
  expect(screen.getByText("first.csv")).toBeTruthy();
  expect(change).toHaveBeenLastCalledWith({
    input_artifact_ids: ["first-file"],
    max_repairs: 1,
  });
  expect(uploads).toBe(2);
});
