import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import AccountGate from "./AccountGate";
import {
  useAccount,
  type AccountStatus,
  type AccountUser,
} from "../account-context";
import { api } from "../api";
import {
  accountStorageKey,
  activeStorageAccount,
  clearPrivateBrowserState,
} from "../lib/account-storage";

afterEach(() => {
  cleanup();
  clearPrivateBrowserState();
  sessionStorage.clear();
  localStorage.clear();
  vi.unstubAllGlobals();
});
const user: AccountUser = {
  id: "synthetic-alice",
  username: "Alice",
  display_name: "Alice",
  is_admin: true,
  enabled: true,
  mfa_enabled: false,
  created_at: "2026-10-30T00:00:00Z",
};
const signedOut: AccountStatus = {
  authenticated: false,
  setup_required: false,
  user: null,
};
const signedIn: AccountStatus = {
  authenticated: true,
  setup_required: false,
  user,
};
const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

function Workspace() {
  const account = useAccount();
  return (
    <>
      <h1>Private workspace for {account.user?.username}</h1>
      <button onClick={() => void account.signOut?.()}>Sign out device</button>
    </>
  );
}
function mount(
  fetch: ReturnType<typeof vi.fn>,
  cache = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
) {
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider client={cache}>
      <AccountGate>
        <Workspace />
      </AccountGate>
    </QueryClientProvider>,
  );
  return cache;
}
function credentials() {
  fireEvent.change(screen.getByLabelText("Username"), {
    target: { value: "Alice" },
  });
  fireEvent.change(screen.getByLabelText("Password"), {
    target: { value: "synthetic password" },
  });
}

it("keeps private work hidden until sign-in and never stores the password", async () => {
  const fetch = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/auth/login") {
      expect(JSON.parse(String(options?.body))).toEqual({
        username: "Alice",
        password: "synthetic password",
      });
      return response(signedIn);
    }
    return response(signedOut);
  });
  mount(fetch);
  await screen.findByRole("heading", { name: "Welcome back." });
  expect(screen.queryByText(/Private workspace/)).toBeNull();
  credentials();
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  await screen.findByRole("heading", { name: "Private workspace for Alice" });
  expect(activeStorageAccount()).toBe(user.id);
  expect(JSON.stringify({ ...sessionStorage, ...localStorage })).not.toContain(
    "synthetic password",
  );
});

it("requests an authenticator or recovery code without issuing a partial session", async () => {
  const fetch = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/auth/login") {
      const body = JSON.parse(String(options?.body));
      return body.second_factor
        ? response(signedIn)
        : response({ detail: "Additional verification is required" }, 403);
    }
    return response(signedOut);
  });
  mount(fetch);
  await screen.findByLabelText("Username");
  credentials();
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  const factor = await screen.findByLabelText(/Authenticator or recovery code/);
  expect(screen.queryByText(/Private workspace/)).toBeNull();
  fireEvent.change(factor, { target: { value: "synthetic-recovery-code" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  await screen.findByRole("heading", { name: "Private workspace for Alice" });
});

it("first setup requires matching passwords and creates an administrator through the real contract", async () => {
  const fetch = vi.fn(async (path: string) =>
    path === "/api/auth/setup"
      ? response(signedIn, 201)
      : response({ ...signedOut, setup_required: true }),
  );
  mount(fetch);
  await screen.findByRole("heading", { name: "Make this station yours." });
  fireEvent.change(screen.getByLabelText("Password"), {
    target: { value: "synthetic password" },
  });
  fireEvent.change(screen.getByLabelText("Confirm password"), {
    target: { value: "different password" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Create your account" }));
  await screen.findByText("Passwords do not match.");
  expect(fetch.mock.calls.some(([path]) => path === "/api/auth/setup")).toBe(
    false,
  );
  fireEvent.change(screen.getByLabelText("Confirm password"), {
    target: { value: "synthetic password" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Create your account" }));
  await screen.findByRole("heading", { name: "Private workspace for Alice" });
});

it("sign-out removes private queries and browser drafts before another account can enter", async () => {
  const fetch = vi.fn(async (path: string) =>
    response(path === "/api/auth/logout" ? signedOut : signedIn),
  );
  const cache = mount(fetch);
  await screen.findByRole("heading", { name: "Private workspace for Alice" });
  cache.setQueryData(["library"], [{ title: "PRIVATE ALICE FILE" }]);
  sessionStorage.setItem(
    accountStorageKey("ai-station:chat-draft:new"),
    "PRIVATE ALICE DRAFT",
  );
  localStorage.setItem("unrelated-application", "retain");
  fireEvent.click(screen.getByRole("button", { name: "Sign out device" }));
  await screen.findByRole("heading", { name: "Welcome back." });
  await waitFor(() =>
    expect(fetch.mock.calls.some(([path]) => path === "/api/auth/logout")).toBe(
      true,
    ),
  );
  expect(cache.getQueryData(["library"])).toBeUndefined();
  expect(JSON.stringify(sessionStorage)).not.toContain("PRIVATE ALICE DRAFT");
  expect(localStorage.getItem("unrelated-application")).toBe("retain");
  expect(activeStorageAccount()).toBeNull();
});

it("locks the workspace on session expiry instead of leaving cached content visible", async () => {
  mount(vi.fn(async () => response(signedIn)));
  await screen.findByRole("heading", { name: "Private workspace for Alice" });
  fireEvent(window, new Event("ai-station:session-expired"));
  await screen.findByRole("heading", { name: "Welcome back." });
  expect(screen.queryByText(/Private workspace/)).toBeNull();
});

it("does not fall back to operator access when the account server has an error", async () => {
  const fetch = vi.fn(async (path: string) => {
    expect(path).toBe("/api/auth");
    return response({ detail: "Temporary station failure" }, 503);
  });
  mount(fetch);
  await screen.findByRole("heading", { name: "Reconnect to your station." });
  expect(fetch.mock.calls.some(([path]) => path === "/api/operator-auth")).toBe(
    false,
  );
});

it("supports the existing single-operator backend only when the account endpoint is absent", async () => {
  const fetch = vi.fn(async (path: string) =>
    path === "/api/auth"
      ? response({ detail: "Not Found" }, 404)
      : response({ session_required: false, authenticated: false }),
  );
  mount(fetch);
  await screen.findByRole("heading", { name: "Private workspace for" });
  fireEvent(window, new Event("ai-station:session-expired"));
  expect(
    screen.getByRole("heading", { name: "Private workspace for" }),
  ).toBeTruthy();
});

it("discards an old account's late request result instead of repopulating private caches", async () => {
  mount(vi.fn(async () => response(signedIn)));
  await screen.findByRole("heading", { name: "Private workspace for Alice" });
  let finish!: (value: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          finish = resolve;
        }),
    ),
  );
  const pending = api("/artifacts");
  clearPrivateBrowserState();
  finish(response([{ title: "PRIVATE OLD RESULT" }]));
  await expect(pending).rejects.toThrow("Account changed");
});
