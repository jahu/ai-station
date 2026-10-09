import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import OperatorGate from "./OperatorLogin";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function mount(fetchImpl: ReturnType<typeof vi.fn>) {
  vi.stubGlobal("fetch", fetchImpl);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <OperatorGate>
        <h1>Workstation</h1>
      </OperatorGate>
    </QueryClientProvider>,
  );
}

it("lets the workstation through when no operator password is stored", async () => {
  mount(
    vi.fn(async () => ({
      ok: true,
      json: async () => ({
        configured: false,
        session_required: false,
        authenticated: false,
        lan_bind_allowed: false,
        bind_host: "127.0.0.1",
        lan_exposure: "disabled",
        reason: "loopback",
      }),
    })),
  );
  await screen.findByRole("heading", { name: "Workstation" });
  expect(screen.queryByRole("button", { name: "Sign in" })).toBeNull();
});

it("requires a loopback session and does not offer LAN publish", async () => {
  let authenticated = false;
  const fetch = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/operator-auth/login" && options?.method === "POST") {
      expect(JSON.parse(String(options.body)).password).toBe(
        "operator-pass-ok",
      );
      authenticated = true;
      return {
        ok: true,
        json: async () => ({
          configured: true,
          session_required: true,
          authenticated: true,
          session_scope: "loopback",
          lan_bind_allowed: false,
          bind_host: "127.0.0.1",
          lan_exposure: "unpublished",
          reason: "loopback",
        }),
      };
    }
    return {
      ok: true,
      json: async () => ({
        configured: true,
        session_required: true,
        authenticated,
        session_scope: "loopback",
        lan_bind_allowed: false,
        bind_host: "127.0.0.1",
        lan_exposure: "unpublished",
        reason: "loopback",
      }),
    };
  });
  mount(fetch);
  await screen.findByRole("heading", { name: "Unlock this workstation." });
  expect(screen.queryByRole("heading", { name: "Workstation" })).toBeNull();
  expect(
    screen.queryByRole("button", { name: /bind|publish|lan/i }),
  ).toBeNull();
  fireEvent.change(screen.getByLabelText("Operator password"), {
    target: { value: "operator-pass-ok" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  await waitFor(() => expect(authenticated).toBe(true));
  await screen.findByRole("heading", { name: "Workstation" });
});
