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
import StudioRendererSetup from "./StudioRendererSetup";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function setup({
  admin = true,
  installed = true,
  ready = false,
  failed = false,
  stale = false,
  active = false,
  loseAck = false,
  fresh = false,
  phase = "",
} = {}) {
  const requests: { path: string; body: Record<string, unknown> }[] = [];
  let history =
    failed || active
      ? [
          {
            id: "task-one",
            manifest_sha256: stale ? "b".repeat(64) : "a".repeat(64),
            resume_allowed: failed,
            progress: { phase },
            run: { id: "run-one", status: active ? "running" : "interrupted" },
          },
        ]
      : [];
  let lost = false;
  const profile = "hyperframes-cpu-linux-amd64-v1";
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const path = String(input);
      const json = (value: unknown, status = 200) =>
        new Response(JSON.stringify(value), {
          status,
          headers: { "Content-Type": "application/json" },
        });
      if (init?.method === "POST") {
        requests.push({ path, body: JSON.parse(String(init.body)) });
        if (loseAck && !lost) {
          lost = true;
          throw new Error("Lost acknowledgement");
        }
        history = [
          {
            id: "task-one",
            manifest_sha256: "a".repeat(64),
            resume_allowed: false,
            progress: { phase },
            run: {
              id: "run-two",
              status: path.endsWith("/cancel") ? "canceled" : "queued",
            },
          },
        ];
        return json(history[0]);
      }
      if (path.includes("/preparations?")) return json(history);
      return json({
        can_prepare: admin,
        installation_available: installed,
        usable_image: ready,
        image: { present: !fresh },
        manifest_sha256: "a".repeat(64),
        recipe: {
          profile,
          preparation_mode: fresh ? "owned_containers" : "existing_image",
          license: "Component licenses",
          license_url:
            "https://github.com/heygen-com/hyperframes/blob/main/LICENSE",
        },
        installation_notice: installed
          ? "Compatible engine is already installed"
          : "No compatible local export engine",
      });
    }),
  );
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={cache}>
      <MemoryRouter>
        <StudioRendererSetup />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { requests, cache };
}
it("requires explicit consent, queues only its fixed profile, and keeps the receipt after a lost acknowledgement", async () => {
  const { requests } = setup({ loseAck: true });
  const button = await screen.findByRole("button", {
    name: "Activate film export",
  });
  expect((button as HTMLButtonElement).disabled).toBe(true);
  expect(requests).toHaveLength(0);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(button);
  await screen.findByText("Lost acknowledgement");
  fireEvent.click(button);
  await waitFor(() => expect(requests).toHaveLength(2));
  expect(requests[0]).toEqual(requests[1]);
  expect(requests[0].body).toEqual({
    client_request_id: expect.any(String),
    profile: "hyperframes-cpu-linux-amd64-v1",
    manifest_sha256: "a".repeat(64),
    license_accepted: true,
  });
  await screen.findByRole("button", { name: "Stop activation" });
});
it("keeps preparation unavailable if the engine is absent", async () => {
  setup({ installed: false });
  await screen.findByText("No compatible local export engine");
  expect(screen.queryByRole("checkbox")).toBeNull();
  expect(
    screen.queryByRole("button", { name: "Activate film export" }),
  ).toBeNull();
});
it("offers no machine-changing controls to members", async () => {
  setup({ admin: false });
  await screen.findByText(
    "Ask a station administrator to prepare film export.",
  );
  expect(screen.queryByRole("checkbox")).toBeNull();
});
it("resumes only a matching reviewed recipe", async () => {
  const { requests } = setup({ failed: true });
  const button = await screen.findByRole("button", {
    name: "Retry activation",
  });
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(button);
  await waitFor(() => expect(requests).toHaveLength(1));
  expect(requests[0].path).toBe(
    "/api/setup/runtimes/preparations/task-one/resume",
  );
  expect(requests[0].body.expected_run_id).toBe("run-one");
});
it("starts a fresh reviewed activation when an older recipe changed", async () => {
  const { requests } = setup({ failed: true, stale: true });
  const button = await screen.findByRole("button", {
    name: "Activate film export",
  });
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(button);
  await waitFor(() => expect(requests).toHaveLength(1));
  expect(requests[0].path).toBe("/api/setup/runtimes");
});
it("lets Stop preserve the prepared shared engine and refreshes actual renderer readiness", async () => {
  const { requests, cache } = setup({ active: true });
  const invalidation = vi.spyOn(cache, "invalidateQueries");
  fireEvent.click(
    await screen.findByRole("button", { name: "Stop activation" }),
  );
  await waitFor(() => expect(requests).toHaveLength(1));
  expect(requests[0].path).toBe(
    "/api/setup/runtimes/preparations/task-one/cancel",
  );
  await waitFor(() =>
    expect(invalidation).toHaveBeenCalledWith({
      queryKey: ["studio-renderer"],
    }),
  );
});
it("shows ready only from native readiness and no activation action", async () => {
  setup({ ready: true });
  await screen.findByText("Ready on this station");
  expect(screen.queryByRole("checkbox")).toBeNull();
});

it("prepares a missing engine with explicit download consent and the same typed setup API", async () => {
  const { requests } = setup({ fresh: true });
  const button = await screen.findByRole("button", {
    name: "Prepare film export",
  });
  expect((button as HTMLButtonElement).disabled).toBe(true);
  expect(
    screen.getByText(/Download size depends on cached components/),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(button);
  await waitFor(() => expect(requests).toHaveLength(1));
  expect(requests[0].body.profile).toBe("hyperframes-cpu-linux-amd64-v1");
  expect(requests[0].body.license_accepted).toBe(true);
  expect(requests[0].body).not.toHaveProperty("command");
});

it("shows actual preparation stages and can stop a fresh installation", async () => {
  const { requests } = setup({ fresh: true, active: true, phase: "sdk" });
  await screen.findByText("Preparing the animation toolkit");
  fireEvent.click(screen.getByRole("button", { name: "Stop preparation" }));
  await waitFor(() => expect(requests).toHaveLength(1));
  expect(requests[0].path).toBe(
    "/api/setup/runtimes/preparations/task-one/cancel",
  );
});
