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
  remote_registration: "loopback-token",
  lan_exposure: "disabled",
  summary: "The local Host Runner is registered over its Unix socket.",
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
      return {
        ok: true,
        json: async () => ({
          ...status,
          configured: true,
          session_required: true,
          authenticated: true,
          session_scope: "loopback",
        }),
      };
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
  expect(
    screen.getByText(/LAN publish is not enabled/, { selector: "p" }),
  ).toBeTruthy();
  expect(screen.queryByDisplayValue("operator-pass")).toBeNull();
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
        path === "/api/nodes"
          ? nodes
          : {
              ...status,
              configured: true,
              session_required: true,
              authenticated: true,
              session_scope: "loopback",
            },
    })),
  );
  await screen.findByText("This workstation");
  expect(
    screen.queryByRole("button", { name: /bind|publish|lan/i }),
  ).toBeNull();
  expect(screen.getByRole("button", { name: "Sign out" })).toBeTruthy();
  expect(
    screen.getByText(/authenticated LAN transport is unpublished/),
  ).toBeTruthy();
});

it("signs out the loopback session without offering LAN publish", async () => {
  const fetch = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/operator-auth/logout" && options?.method === "POST") {
      return {
        ok: true,
        json: async () => ({
          ...status,
          configured: true,
          session_required: true,
          authenticated: false,
          session_scope: "loopback",
        }),
      };
    }
    if (path === "/api/operator-auth") {
      return {
        ok: true,
        json: async () => ({
          ...status,
          configured: true,
          session_required: true,
          authenticated: true,
          session_scope: "loopback",
        }),
      };
    }
    return { ok: true, json: async () => nodes };
  });
  mount(fetch);
  await screen.findByRole("button", { name: "Sign out" });
  expect(
    screen.queryByRole("button", { name: /bind|publish|lan/i }),
  ).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
  await waitFor(() =>
    expect(
      fetch.mock.calls.some(
        (call) =>
          call[0] === "/api/operator-auth/logout" &&
          (call[1] as RequestInit | undefined)?.method === "POST",
      ),
    ).toBe(true),
  );
});

it("shows an invitation token once and omits it from later node lists", async () => {
  const remote = {
    id: "n1",
    name: "Studio GPU",
    kind: "host-runner",
    transport: "unpublished",
    ownership: "remote",
    status: "pending",
    authenticated: false,
    token_issued: true,
  };
  const fetch = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/nodes/invitations" && options?.method === "POST") {
      expect(JSON.parse(String(options.body)).name).toBe("Studio GPU");
      return {
        ok: true,
        json: async () => ({ ...remote, token: "aisn_secret-token" }),
      };
    }
    if (path === "/api/nodes") {
      return {
        ok: true,
        json: async () => ({ ...nodes, items: [...nodes.items, remote] }),
      };
    }
    return {
      ok: true,
      json: async () => ({
        ...status,
        configured: true,
        session_required: true,
        authenticated: true,
        session_scope: "loopback",
      }),
    };
  });
  mount(fetch);
  await screen.findByText("This workstation");
  fireEvent.change(screen.getByLabelText("Remote node name"), {
    target: { value: "Studio GPU" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Issue invitation" }));
  await screen.findByText(/aisn_secret-token/);
  await screen.findByText("Studio GPU");
  expect(
    screen.getByText(/host-runner · unpublished · remote · pending/),
  ).toBeTruthy();
  const listCalls = fetch.mock.calls.filter(([path]) => path === "/api/nodes");
  expect(listCalls.length).toBeGreaterThan(0);
});
