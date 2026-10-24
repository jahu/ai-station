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
import DataPreview from "./DataPreview";
import type { Artifact } from "../api";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function mount(failed = false, jsonFormat = false) {
  const writes: unknown[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method) writes.push(JSON.parse(String(init.body)));
      return {
        ok: true,
        json: async () => ({
          id: "preview-run",
          status: failed ? "failed" : "succeeded",
          error_message: failed ? "Data input changed before inspection" : "",
          metadata: failed
            ? {}
            : {
                data_preview: {
                  sheets: [
                    {
                      name: jsonFormat ? "JSON" : "Sales",
                      column_names: jsonFormat ? ["Key", "Value"] : undefined,
                      row_count: 50,
                      column_count: 2,
                      formula_count: 0,
                      preview: [["<script>alert(1)</script>", "27"]],
                    },
                    {
                      name: "Totals",
                      row_count: 1,
                      column_count: 1,
                      formula_count: 1,
                      preview: [["[Formula — not evaluated]"]],
                    },
                  ],
                },
              },
        }),
      };
    }),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <DataPreview
          artifact={
            {
              id: "input",
              type: "document",
              mime_type: "text/csv",
              original_filename: "sales.csv",
              size_bytes: 20,
              created_at: "2026-10-15T12:00:00Z",
              run_id: null,
              parent_artifact_ids: [],
              metadata: { data_inspection_run_id: "preview-run" },
            } as Artifact
          }
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return writes;
}
it("renders a literal read-only table and changes sheets without executing workloads", async () => {
  const writes = mount();
  await screen.findByRole("table", { name: "Sales data preview" });
  expect(screen.getByText("<script>alert(1)</script>")).toBeTruthy();
  expect(document.querySelector("script")).toBeNull();
  fireEvent.change(screen.getByRole("combobox", { name: "Sheet" }), {
    target: { value: "1" },
  });
  expect(
    screen.getByRole("table", { name: "Totals data preview" }),
  ).toBeTruthy();
  expect(screen.getByText("[Formula — not evaluated]")).toBeTruthy();
  expect(writes).toEqual([]);
  expect(
    screen
      .getByRole("link", { name: "Inspect preview Run" })
      .getAttribute("href"),
  ).toBe("/runs/preview-run");
});
it("shows a failed inspection and retries only the selected input after an explicit click", async () => {
  const writes = mount(true);
  await screen.findByText("Data input changed before inspection");
  expect(screen.queryByRole("table")).toBeNull();
  expect(writes).toEqual([]);
  fireEvent.click(screen.getByRole("button", { name: "Inspect data" }));
  await waitFor(() => expect(writes).toEqual([{ artifact_id: "input" }]));
});

it("uses real JSON field headers and renders source text without evaluation", async () => {
  mount(false, true);
  await screen.findByRole("table", { name: "JSON data preview" });
  expect(screen.getByRole("columnheader", { name: "Key" })).toBeTruthy();
  expect(screen.getByRole("columnheader", { name: "Value" })).toBeTruthy();
  expect(screen.getByText("<script>alert(1)</script>")).toBeTruthy();
  expect(document.querySelector("script")).toBeNull();
});
