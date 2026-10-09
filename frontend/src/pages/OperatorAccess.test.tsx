import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import OperatorAccess from "./OperatorAccess";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const status = {
  configured: false,
  bind_host: "127.0.0.1",
  lan_exposure: "disabled",
  lan_bind_allowed: false,
  reason: "The UI/API stays on loopback. LAN publish is not enabled.",
};

const nodes = {
  items: [
    {
      id: "local",
      name: "This workstation",
      kind: "host-runner",
      transport: "unix-socket",
      ownership: "local",
      authenticated: true,
    },
  ],
  remote_registration: "unavailable",
  lan_exposure: "disabled",
  summary: "Only the private local Host Runner is registered.",
};

function mount(fetchImpl: ReturnType<typeof vi.fn>) {
  vi.stubGlobal("fetch", fetchImpl);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <OperatorAccess />
    </QueryClientProvider>,
  );
}

it("stores an operator password without displaying it later", async () => {
  let configured = false;
  const fetch = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/operator-auth" && options?.method === "PUT") {
      configured = true;
      expect(JSON.parse(String(options.body)).password).toBe("operator-pass");
      return { ok: true, json: async () => ({ ...status, configured: true }) };
    }
    if (path === "/api/operator-auth") {
      return {
        ok: true,
        json: async () => ({ ...status, configured }),
      };
    }
    return { ok: true, json: async () => nodes };
  });
  mount(fetch);
  await screen.findByText("This workstation");
  expect(screen.getByText(/LAN publish is not enabled/)).toBeTruthy();
  expect(screen.queryByText("operator-pass")).toBeNull();
  fireEvent.change(screen.getByLabelText("Operator password"), {
    target: { value: "operator-pass" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Store password" }));
  await waitFor(() => expect(configured).toBe(true));
  await screen.findByText(/operator password stored/);
  expect(screen.queryByDisplayValue("operator-pass")).toBeNull();
});

it("does not offer a LAN bind control", async () => {
  mount(
    vi.fn(async (path: string) => ({
      ok: true,
      json: async () =>
        path === "/api/nodes" ? nodes : { ...status, configured: true },
    })),
  );
  await screen.findByText("This workstation");
  expect(
    screen.queryByRole("button", { name: /bind|publish|lan/i }),
  ).toBeNull();
  expect(
    screen.getByText(/authenticated LAN transport is unpublished/),
  ).toBeTruthy();
});
