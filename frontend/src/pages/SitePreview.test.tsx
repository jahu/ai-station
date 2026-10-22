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
import SitePreview from "./SitePreview";

const queryClients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  queryClients.forEach((client) => client.clear());
  queryClients.length = 0;
  vi.unstubAllGlobals();
});
function show() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  queryClients.push(client);
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/preview/build/archive"]}>
        <Routes>
          <Route
            path="/preview/:sourceRunId/:artifactId"
            element={<SitePreview />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
function backend({
  existing = true,
  failAction = false,
  available = true,
  agentId = null as string | null,
} = {}) {
  const requests: { path: string; body: Record<string, unknown> }[] = [];
  const frame = {
    artifact_id: "frame",
    revision: 0,
    width: 1240,
    height: 800,
    title: "Counter",
    path: "index.html",
    blocked_requests: 1,
  };
  const preview = {
    id: "preview",
    task_id: "inspection-task",
    status: "running",
    parameters: { source: { artifact_id: "archive" } },
    metadata: { frame },
  };
  let rejected = false;
  const fetch = vi.fn(async (path: string, options?: RequestInit) => {
    if (options?.method === "POST") {
      const body = JSON.parse(options.body as string);
      requests.push({ path, body });
      if (path.endsWith("/actions") && failAction && !rejected) {
        rejected = true;
        throw new Error("Connection lost");
      }
      if (path.endsWith("/actions"))
        return {
          ok: true,
          json: async () => ({ id: "action", status: "queued" }),
        };
      if (path.endsWith("/close"))
        return {
          ok: true,
          json: async () => ({ id: "close", status: "queued" }),
        };
      return { ok: true, json: async () => preview };
    }
    const value =
      path === "/api/runs/build"
        ? { id: "build", task_id: "source-task", agent_id: agentId }
        : path.includes("capabilities")
          ? { available, reason: "Preview image is not configured" }
          : path.includes("?source_task_id")
            ? existing
              ? [preview]
              : []
            : path === "/api/runs/action"
              ? { id: "action", status: "succeeded" }
              : path === "/api/runs/close"
                ? {
                    id: "close",
                    executor_type: "site_preview_close",
                    status: "running",
                  }
                : preview;
    return { ok: true, json: async () => value };
  });
  vi.stubGlobal("fetch", fetch);
  return { requests, fetch };
}
it("opens a phone build only after an explicit click and preserves source identity", async () => {
  const { requests } = backend({ existing: false });
  show();
  const button = await screen.findByRole("button", { name: "Open preview" });
  await waitFor(() => expect(button.hasAttribute("disabled")).toBe(false));
  expect(requests).toHaveLength(0);
  fireEvent.change(screen.getByRole("combobox", { name: "Preview viewport" }), {
    target: { value: "phone" },
  });
  fireEvent.click(button);
  await screen.findByRole("img", { name: "Preview: Counter" });
  expect(requests[0].body).toMatchObject({
    source_run_id: "build",
    artifact_id: "archive",
    width: 390,
    height: 844,
  });
  expect(document.querySelector("iframe,object,embed,script")).toBeNull();
  expect(
    screen
      .getByRole("link", { name: "← Back to workspace" })
      .getAttribute("href"),
  ).toBe("/coding/source-task");
});
it("scales pointer coordinates to the captured viewport and sends its exact revision", async () => {
  const { requests } = backend();
  show();
  const image = await screen.findByRole("img", { name: "Preview: Counter" });
  vi.spyOn(image, "getBoundingClientRect").mockReturnValue({
    left: 10,
    top: 20,
    width: 620,
    height: 400,
  } as DOMRect);
  const stage = screen.getByRole("button", { name: /Interactive website/ });
  fireEvent.click(stage, { detail: 1, clientX: 60, clientY: 60 });
  await waitFor(() => expect(requests).toHaveLength(1));
  expect(requests[0]).toMatchObject({
    path: "/api/site-previews/preview/actions",
    body: { expected_revision: 0, action: { kind: "click", x: 100, y: 80 } },
  });
});
it("retries an ambiguous text submission with the same receipt and literal text", async () => {
  const { requests } = backend({ failAction: true });
  show();
  await screen.findByRole("img", { name: "Preview: Counter" });
  const literal = '<script>fetch("http://127.0.0.1")</script>';
  fireEvent.change(
    screen.getByRole("textbox", { name: "Text for focused website field" }),
    { target: { value: literal } },
  );
  fireEvent.click(screen.getByRole("button", { name: "Type into page" }));
  const retry = await screen.findByRole("button", {
    name: "Retry same interaction",
  });
  expect(
    screen.getByRole("button", { name: "Reset page" }).hasAttribute("disabled"),
  ).toBe(true);
  fireEvent.click(retry);
  await waitFor(() => expect(requests).toHaveLength(2));
  expect(requests[0].body).toEqual(requests[1].body);
  expect(requests[0].body.action).toEqual({ kind: "text", text: literal });
});
it("keeps close available while an interaction needs reconciliation", async () => {
  const { requests } = backend({ failAction: true });
  show();
  await screen.findByRole("img", { name: "Preview: Counter" });
  fireEvent.click(screen.getByRole("button", { name: "Reset page" }));
  await screen.findByRole("button", { name: "Retry same interaction" });
  fireEvent.click(screen.getByRole("button", { name: "Close preview" }));
  await waitFor(() =>
    expect(requests[1].path).toBe("/api/site-previews/preview/close"),
  );
});
it("shows an unavailable capability without starting any workload", async () => {
  const { requests } = backend({ existing: false, available: false });
  show();
  await screen.findByText("Preview image is not configured");
  expect(
    screen
      .getByRole("button", { name: "Open preview" })
      .hasAttribute("disabled"),
  ).toBe(true);
  expect(requests).toHaveLength(0);
});

it("returns agent-generated builds to the agent workspace", async () => {
  backend({ agentId: "builder" });
  show();
  await screen.findByRole("img", { name: "Preview: Counter" });
  expect(
    screen
      .getByRole("link", { name: "← Back to workspace" })
      .getAttribute("href"),
  ).toBe("/agents/builder?view=workspace");
});
