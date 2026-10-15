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
  await screen.findByText(/Operator password stored/);
  expect(screen.queryByDisplayValue("operator-pass")).toBeNull();
});

it("describes device sessions and idle timeout", async () => {
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
              session_idle_seconds: 1800,
              session_max_age_seconds: 43200,
              session_cookie: {
                httponly: true,
                samesite: "strict",
                secure: false,
                path: "/",
              },
            },
    })),
  );
  await screen.findByText("This workstation");
  expect(screen.getByText(/Each device has its own session/)).toBeTruthy();
  expect(
    screen.getByText(/30 minutes\s+idle or 12 hours from sign-in/),
  ).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: /bind|publish|lan/i }),
  ).toBeNull();
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
  expect(screen.getByText(/Private network access is off/)).toBeTruthy();
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

it("moves through nodes with arrow keys", async () => {
  const remote = {
    id: "node-two",
    name: "Studio GPU",
    kind: "host-runner",
    transport: "unpublished",
    ownership: "remote",
    status: "pending",
    authenticated: false,
  };
  mount(
    vi.fn(async (path: string) => ({
      ok: true,
      json: async () =>
        path === "/api/nodes"
          ? { ...nodes, items: [...nodes.items, remote] }
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
  const first = screen
    .getByText("This workstation")
    .closest("[data-list-index]") as HTMLElement;
  const second = screen.getByRole("button", {
    name: "Revoke Studio GPU node-two",
  });
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(screen.getByRole("region", { name: "Nodes" })).toBeTruthy();
  expect(
    screen.getByText(/Remote execution transport stays unpublished/),
  ).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: /bind|publish|lan/i }),
  ).toBeNull();
  fireEvent.keyDown(first.closest(".diagnostic-list") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  expect(document.activeElement).toBe(
    screen.getByText("Studio GPU").closest("[data-list-index]"),
  );
  fireEvent.keyDown(second.closest(".diagnostic-list") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
});

it("shows the private phone URL and protects the password while LAN is active", async () => {
  mount(
    vi.fn(async (path: string) => ({
      ok: true,
      json: async () =>
        path === "/api/nodes"
          ? nodes
          : {
              ...status,
              configured: true,
              authenticated: true,
              access_urls: ["http://192.168.20.5:8765"],
              lan_bind_allowed: true,
              password_removal_allowed: false,
              lan_exposure: "private",
              reason: "Private network access requires the operator password.",
            },
    })),
  );
  const link = await screen.findByRole("link", {
    name: "http://192.168.20.5:8765",
  });
  expect(link.getAttribute("href")).toBe("http://192.168.20.5:8765");
  expect(screen.queryByRole("button", { name: "Remove password" })).toBeNull();
  expect(screen.getByText(/Use the same operator password/)).toBeTruthy();
});
