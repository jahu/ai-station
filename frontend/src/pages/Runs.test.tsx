import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { RunDetail, Runs } from "./Runs";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("shows the actual API failure instead of an empty successful history", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({ detail: "Database unavailable" }),
    }),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Runs />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect((await screen.findByRole("alert")).textContent).toContain(
    "Database unavailable",
  );
});

it("requests the selected status and links persisted runs to their inspector", async () => {
  const fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => [
      {
        id: "one",
        capability: "image.generate",
        executor_type: "photo_pipe",
        execution_target: "host",
        status: "running",
        created_at: "2026-01-01T00:00:00Z",
      },
    ],
  });
  vi.stubGlobal("fetch", fetch);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Runs />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(
    (await screen.findByRole("link", { name: /image.generate/ })).getAttribute(
      "href",
    ),
  ).toBe("/runs/one");
  fireEvent.change(screen.getByRole("combobox", { name: "Filter by status" }), {
    target: { value: "running" },
  });
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith("/api/runs?status=running", undefined),
  );
});

it("restores combined filters from the URL and resets paging when applying a change", async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter
        initialEntries={["/runs?status=failed&executor=chat&offset=100"]}
      >
        <Runs />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByText("No runs in this view");
  expect(fetch).toHaveBeenCalledWith(
    "/api/runs?status=failed&executor=chat&offset=100",
    undefined,
  );
  fireEvent.click(screen.getByText("More filters"));
  fireEvent.change(screen.getByLabelText("Capability"), {
    target: { value: "chat.completion" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/runs?status=failed&capability=chat.completion&executor=chat",
      undefined,
    ),
  );
  expect(screen.getByText("Page 1 · up to 100 runs")).toBeTruthy();
});
it("lets the user grant a parked agent Run without starting it from the inspector", async () => {
  vi.stubGlobal(
    "EventSource",
    class {
      close() {}
      addEventListener() {}
    },
  );
  let run = {
    id: "parked",
    capability: "agent.execute",
    executor_type: "agent",
    execution_target: "container",
    status: "waiting_for_approval",
    created_at: "2026-10-09T12:00:00Z",
    started_at: null,
    finished_at: null,
    actual_gpu: null,
    requested_gpu: "none",
    parameters: {},
    effective_permissions: [],
    summary: "",
    error_type: "",
    error_message: "",
    worker_id: null,
    approval: {
      id: "a1",
      action: "agent.execute",
      reason: "This agent requires approval before each Run",
      risk: "medium",
      payload: {},
      requested_at: "2026-10-09T12:00:00Z",
      resolved_at: null as string | null,
      resolution: "pending",
    },
  };
  const fetch = vi.fn(async (url: string, options?: RequestInit) => {
    if (options && String(url).includes("/approval")) {
      const body = JSON.parse(options.body as string);
      run = {
        ...run,
        status: body.resolution === "granted" ? "queued" : "canceled",
        approval: {
          ...run.approval,
          resolution: body.resolution,
          resolved_at: "2026-10-09T12:01:00Z",
        },
      };
    }
    return {
      ok: true,
      json: async () =>
        String(url).includes("/events") || String(url).includes("/artifacts")
          ? []
          : run,
    };
  });
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={["/runs/parked"]}>
        <Routes>
          <Route path="/runs/:id" element={<RunDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByRole("heading", { name: "Approval required" });
  fireEvent.click(screen.getByRole("button", { name: "Approve and queue" }));
  await waitFor(() =>
    expect(
      fetch.mock.calls.some(
        (call) =>
          String(call[0]).includes("/approval") &&
          JSON.parse(String(call[1]?.body)).resolution === "granted",
      ),
    ).toBe(true),
  );
});
