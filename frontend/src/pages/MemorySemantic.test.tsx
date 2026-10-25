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
import MemorySemantic from "./MemorySemantic";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const local = {
  id: "multilingual-e5-small-int8-v1",
  name: "Multilingual E5 Small",
  size_bytes: 135390915,
  installed: false,
  available: true,
};
const setup = {
  configured: false,
  backend: "endpoint",
  revision: 7,
  endpoint: "",
  model: "",
  dimension: null,
  indexed_count: 0,
  memory_count: 3,
  local_model: local,
};
function view(scope = "", target = "") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const tree = (scope: string, target: string) => (
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <MemorySemantic scope={scope} target={target} />
      </MemoryRouter>
    </QueryClientProvider>
  );
  const result = render(tree(scope, target));
  return {
    ...result,
    scope: (scope: string, target = "") => result.rerender(tree(scope, target)),
  };
}

it("requires explicit model download consent and shows preparation with owned Stop", async () => {
  let current: Record<string, unknown> = setup;
  const run = {
    id: "prepare-1",
    status: "running",
    capability: "memory.embed.prepare",
    metadata: {},
    created_at: "2026-10-25T11:00:00Z",
  };
  const calls: [string, RequestInit?][] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      calls.push([url, options]);
      if (url.endsWith("/prepare")) current = { ...setup, prepare_run: run };
      return {
        ok: true,
        json: async () => (url.endsWith("/setup") ? current : run),
      };
    }),
  );
  view();
  const button = await screen.findByRole("button", {
    name: "Set up semantic memory",
  });
  expect((button as HTMLButtonElement).disabled).toBe(true);
  expect(calls.every(([, o]) => !o?.method)).toBe(true);
  fireEvent.click(
    screen.getByRole("checkbox", {
      name: /Download the local model and tokenizer/,
    }),
  );
  fireEvent.click(button);
  fireEvent.click(await screen.findByRole("button", { name: "Stop" }));
  await waitFor(() =>
    expect(calls.some(([u]) => u.endsWith("/prepare-1/cancel"))).toBe(true),
  );
  const body = JSON.parse(
    String(calls.find(([u]) => u.endsWith("/prepare"))?.[1]?.body),
  );
  expect(body).toEqual({
    expected_revision: 7,
    model_id: local.id,
    confirm_download: true,
  });
  expect(screen.getByText("LOCAL · CPU")).toBeTruthy();
});

it("shows inline semantic matches and freezes the requested scope during a delayed reply", async () => {
  const current = {
    ...setup,
    configured: true,
    backend: "local_cpu",
    dimension: 384,
    model: local.id,
    indexed_count: 3,
    local_model: { ...local, installed: true },
  };
  let resolve!: (value: unknown) => void;
  let body: unknown;
  const run = {
    id: "search-1",
    status: "succeeded",
    capability: "memory.embed.search",
    created_at: "2026-10-25T11:00:00Z",
    metadata: {
      results: [
        {
          id: "memory-1",
          content: "Preferuję uczyć się na przykładach",
          scope: "global",
          score: 0.91,
        },
      ],
    },
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      if (url.endsWith("/search")) {
        body = JSON.parse(String(options?.body));
        return new Promise((r) => {
          resolve = r;
        });
      }
      return {
        ok: true,
        json: async () => (url.endsWith("/setup") ? current : run),
      };
    }),
  );
  const v = view("global");
  fireEvent.change(
    await screen.findByRole("textbox", { name: "Semantic query" }),
    { target: { value: "Jak lubię się uczyć?" } },
  );
  fireEvent.click(screen.getByRole("button", { name: /Search by meaning/ }));
  await waitFor(() => expect(resolve).toBeTypeOf("function"));
  expect(body).toEqual({ query: "Jak lubię się uczyć?", scope: "global" });
  v.scope("project", "project-id");
  resolve({ ok: true, json: async () => run });
  await screen.findByText(/The scope changed/);
  expect(screen.queryByText("Preferuję uczyć się na przykładach")).toBeNull();
  v.scope("global");
  expect(await screen.findByRole("link", { name: /Preferuję/ })).toHaveProperty(
    "href",
    expect.stringContaining("/memory/memory-1"),
  );
  expect(screen.getByText("global · Similarity 91%")).toBeTruthy();
});

it("keeps a failed automatic index distinct from successful model preparation", async () => {
  const current = {
    ...setup,
    configured: true,
    backend: "local_cpu",
    local_model: { ...local, installed: true },
    prepare_run: {
      id: "prepare",
      status: "succeeded",
      created_at: "2026-10-25T10:00:00Z",
    },
    index_run: {
      id: "index",
      status: "failed",
      error_message: "Indexing budget expired; completed vectors were retained",
      created_at: "2026-10-25T10:01:00Z",
    },
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, json: async () => current })),
  );
  view();
  expect(await screen.findByText(/Indexing budget expired/)).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "Inspect operation" }),
  ).toHaveProperty("href", expect.stringContaining("/runs/index"));
  expect(
    screen.getByRole("button", { name: "Index remaining memories" }),
  ).toHaveProperty("disabled", false);
});
