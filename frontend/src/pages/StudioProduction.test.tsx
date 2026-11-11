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
import StudioProduction from "./StudioProduction";
import type { StudioRevision } from "./studio-material";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function setup({
  active = false,
  failed = false,
  available = true,
  disabled = false,
  loseAck = false,
  checking = false,
} = {}) {
  const requests: { path: string; body: Record<string, unknown> }[] = [];
  let lost = false;
  let checks = 0;
  const row = {
    root_run: {
      id: "production-one",
      task_id: "task-one",
      parameters: {
        studio_revision_id: "original",
        request: {
          client_request_id: "old-receipt",
          revision_id: "original",
          bindings: [],
          image_model: "chosen-model",
        },
      },
    },
    status: failed ? "failed" : "running",
    runs: [],
    output: null,
    failed_run: failed ? { error_message: "The render failed" } : null,
    measured_revision_id: "measured",
  };
  let history = active || failed ? [row] : [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const path = String(input);
      const json = (value: unknown) =>
        new Response(JSON.stringify(value), {
          headers: { "Content-Type": "application/json" },
        });
      if (init?.method === "POST") {
        requests.push({ path, body: JSON.parse(String(init.body)) });
        if (loseAck && !lost) {
          lost = true;
          throw Error("Lost acknowledgement");
        }
        history = [
          { ...row, status: path.endsWith("/stop") ? "canceled" : "running" },
        ];
        return json(row.root_run);
      }
      if (path.endsWith("/productions")) return json(history);
      checks += 1;
      return json({
        available: checking ? checks > 1 : available,
        readiness:
          checking && checks === 1
            ? "checking"
            : available
              ? "ready"
              : "unavailable",
      });
    }),
  );
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={cache}>
      <MemoryRouter>
        <StudioProduction
          materialId="material"
          revision={{ id: "original" } as StudioRevision}
          disabled={disabled}
          selectedTakes={{ 2: "chosen-take" }}
          onVersion={vi.fn()}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return requests;
}
it("freezes selected takes and keeps the same receipt after a lost acknowledgement", async () => {
  const requests = setup({ loseAck: true });
  const button = await screen.findByRole("button", { name: "Produce film" });
  await waitFor(() =>
    expect((button as HTMLButtonElement).disabled).toBe(false),
  );
  fireEvent.click(button);
  await screen.findByText("Lost acknowledgement");
  fireEvent.click(button);
  await waitFor(() => expect(requests).toHaveLength(2));
  expect(requests[0]).toEqual(requests[1]);
  expect(requests[0].body.bindings).toEqual([
    { scene: 2, artifact_id: "chosen-take" },
  ]);
});
it("retries the frozen original request with completed-media reuse", async () => {
  const requests = setup({ failed: true });
  const button = await screen.findByRole("button", {
    name: "Continue · reuse completed media",
  });
  await waitFor(() =>
    expect((button as HTMLButtonElement).disabled).toBe(false),
  );
  fireEvent.click(button);
  await waitFor(() => expect(requests).toHaveLength(1));
  expect(requests[0].body).toMatchObject({
    revision_id: "original",
    image_model: "chosen-model",
    reuse_from_run_id: "production-one",
  });
  expect(requests[0].body.client_request_id).not.toBe("old-receipt");
});
it("stops the whole owned production instead of a completed planning Run", async () => {
  const requests = setup({ active: true });
  fireEvent.click(
    await screen.findByRole("button", { name: "Stop production" }),
  );
  await waitFor(() => expect(requests).toHaveLength(1));
  expect(requests[0].path).toBe(
    "/api/studio/materials/material/productions/production-one/stop",
  );
});
it("blocks expensive production when export is unavailable or edits are unsaved", async () => {
  const requests = setup({ available: false, disabled: true });
  await screen.findByText(/Prepare film export below/);
  expect(
    (screen.getByRole("button", { name: "Produce film" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  expect(requests).toHaveLength(0);
});

it("automatically enables production when initial native verification completes", async () => {
  setup({ checking: true });
  await screen.findByText("Checking local film export…");
  const button = screen.getByRole("button", {
    name: "Produce film",
  }) as HTMLButtonElement;
  expect(button.disabled).toBe(true);
  await waitFor(() => expect(button.disabled).toBe(false), { timeout: 3000 });
  expect(screen.queryByText("Checking local film export…")).toBeNull();
});
