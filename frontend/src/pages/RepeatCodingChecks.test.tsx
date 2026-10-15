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
import type { Run } from "../api";
import RepeatCodingChecks from "./RepeatCodingChecks";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const source = {
  id: "source",
  task_id: "task",
  status: "succeeded",
  metadata: {},
} as Run;
const validation = {
  id: "checks",
  status: "succeeded",
  parameters: { commands: [{ kind: "test", argv: ["npm", "run", "test"] }] },
  metadata: { process_confirmed_gone: true },
} as unknown as Run;
function show(run = validation, proposal = source) {
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const invalidate = vi.spyOn(cache, "invalidateQueries");
  render(
    <QueryClientProvider client={cache}>
      <MemoryRouter>
        <textarea aria-label="Draft" defaultValue="Keep my next instruction" />
        <RepeatCodingChecks source={proposal} validation={run} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return invalidate;
}

it("queues recorded checks in place with only the guarded validation id", async () => {
  const fetcher = vi.fn(async () => ({
    ok: true,
    json: async () => ({ id: "repeat" }),
  }));
  vi.stubGlobal("fetch", fetcher);
  const invalidate = show();
  fireEvent.click(screen.getByRole("button", { name: "Run checks again" }));
  await screen.findByRole("link", {
    name: "Checks queued · inspect execution →",
  });
  expect(fetcher).toHaveBeenCalledWith(
    "/api/coding/runs/source/checks",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ expected_validation_run_id: "checks" }),
    }),
  );
  expect(
    (screen.getByRole("textbox", { name: "Draft" }) as HTMLTextAreaElement)
      .value,
  ).toBe("Keep my next instruction");
  expect(screen.getByRole("link").getAttribute("href")).toBe("/runs/repeat");
  expect(invalidate).toHaveBeenCalledWith({
    queryKey: ["coding-session", "task"],
  });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["run", "source"] });
});

it("disables duplicate requests while pending and keeps retry errors in place", async () => {
  let finish!: (value: unknown) => void;
  const pending = new Promise((resolve) => {
    finish = resolve;
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(() => pending),
  );
  show();
  fireEvent.click(screen.getByRole("button", { name: "Run checks again" }));
  expect(
    (
      screen.getByRole("button", {
        name: "Queuing checks…",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  finish({
    ok: false,
    json: async () => ({ detail: "Another check is active" }),
  });
  await screen.findByText("Another check is active");
  expect(
    (screen.getByRole("textbox", { name: "Draft" }) as HTMLTextAreaElement)
      .value,
  ).toBe("Keep my next instruction");
  await waitFor(() =>
    expect(
      (
        screen.getByRole("button", {
          name: "Run checks again",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false),
  );
});

it("requires terminal checks and confirmed ownership rather than guessing a process stopped", () => {
  show({ ...validation, status: "running" } as Run);
  expect(screen.queryByRole("button")).toBeNull();
  cleanup();
  show({
    ...validation,
    status: "interrupted",
    metadata: { dispatch_attempted: true },
  } as Run);
  expect(screen.queryByRole("button")).toBeNull();
  expect(screen.getByText(/Inspect the previous check process/)).toBeTruthy();
});

it("allows explicitly undispatched canceled checks and links prior history", () => {
  show({
    ...validation,
    status: "canceled",
    parameters: { ...validation.parameters, rerun_of: "previous" },
    metadata: { dispatch_attempted: false },
  } as Run);
  expect(screen.getByRole("button", { name: "Run checks again" })).toBeTruthy();
  expect(
    screen
      .getByRole("link", { name: "Previous checks →" })
      .getAttribute("href"),
  ).toBe("/runs/previous");
});

it("does not repeat superseded or failed proposals", () => {
  show(validation, {
    ...source,
    metadata: { continuation_run_id: "later" },
  } as Run);
  expect(screen.queryByRole("button")).toBeNull();
  cleanup();
  show(validation, { ...source, status: "failed" } as Run);
  expect(screen.queryByRole("button")).toBeNull();
});
