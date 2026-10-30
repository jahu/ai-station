import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AccountContext, type AccountUser } from "../account-context";
import AccountUsers from "./AccountUsers";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const admin: AccountUser = {
  id: "admin",
  username: "Alice",
  display_name: "Alice",
  is_admin: true,
  enabled: true,
  mfa_enabled: true,
  created_at: "2026-10-30T00:00:00Z",
};
const member: AccountUser = {
  ...admin,
  id: "member",
  username: "Bob",
  display_name: "Bob",
  is_admin: false,
  mfa_enabled: false,
};
const reply = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
function mount(fetch: ReturnType<typeof vi.fn>, user = admin) {
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <AccountContext.Provider value={{ mode: "accounts", user }}>
        <AccountUsers />
      </AccountContext.Provider>
    </QueryClientProvider>,
  );
}
it("does not request the user directory for a member", async () => {
  const fetch = vi.fn();
  mount(fetch, member);
  expect(screen.getByText("Administrator access required")).toBeTruthy();
  expect(fetch).not.toHaveBeenCalled();
});
it("creates a private member account and keeps password confirmation local", async () => {
  const fetch = vi.fn(async (url: string, options?: RequestInit) => {
    if (options?.method === "POST") {
      expect(url).toBe("/api/admin/users");
      expect(JSON.parse(String(options.body))).toEqual({
        username: "Charlie",
        password: "synthetic new password",
        is_admin: false,
      });
      return reply({ ...member, id: "new", username: "Charlie" }, 201);
    }
    return reply([admin, member]);
  });
  mount(fetch);
  await screen.findByRole("button", { name: "Manage Bob" });
  fireEvent.click(screen.getByRole("button", { name: "Add user" }));
  fireEvent.change(screen.getByLabelText("Username"), {
    target: { value: "Charlie" },
  });
  fireEvent.change(screen.getByLabelText("Initial password"), {
    target: { value: "synthetic new password" },
  });
  fireEvent.change(screen.getByLabelText("Confirm password"), {
    target: { value: "mismatch password" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Create user" }));
  expect(await screen.findByText("Passwords do not match.")).toBeTruthy();
  expect(
    fetch.mock.calls.filter(([, options]) => options?.method === "POST"),
  ).toHaveLength(0);
  fireEvent.change(screen.getByLabelText("Confirm password"), {
    target: { value: "synthetic new password" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Create user" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});
it("explains work cancellation before disabling an account and preserves its role", async () => {
  const fetch = vi.fn(async (url: string, options?: RequestInit) => {
    if (options?.method === "PATCH") {
      expect(url).toBe("/api/admin/users/member");
      expect(JSON.parse(String(options.body))).toEqual({
        enabled: false,
        is_admin: false,
      });
      return reply({ ...member, enabled: false });
    }
    return reply([admin, member]);
  });
  mount(fetch);
  fireEvent.click(await screen.findByRole("button", { name: "Manage Bob" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Account enabled" }));
  expect(screen.getByText(/pauses their agents and cancels/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Save access" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});
it("protects the last enabled administrator in the UI as well as the server", async () => {
  mount(vi.fn(async () => reply([admin, member])));
  fireEvent.click(await screen.findByRole("button", { name: "Manage Alice" }));
  expect(
    screen.getByRole("combobox", { name: "Role" }).hasAttribute("disabled"),
  ).toBe(true);
  expect(
    screen
      .getByRole("checkbox", { name: "Account enabled" })
      .hasAttribute("disabled"),
  ).toBe(true);
});
it("requires the administrator's password and factor to reset another user's credentials", async () => {
  const fetch = vi.fn(async (url: string, options?: RequestInit) => {
    if (options?.method === "POST") {
      expect(url).toBe("/api/admin/users/member/credentials");
      expect(JSON.parse(String(options.body))).toEqual({
        password: "synthetic admin password",
        new_password: "synthetic reset password",
        reset_mfa: false,
        second_factor: "123456",
      });
      return reply(member);
    }
    return reply([admin, member]);
  });
  mount(fetch);
  fireEvent.click(await screen.findByRole("button", { name: "Manage Bob" }));
  fireEvent.click(screen.getByRole("button", { name: "Reset password" }));
  for (const [label, value] of [
    ["New password", "synthetic reset password"],
    ["Confirm password", "synthetic reset password"],
    ["Your administrator password", "synthetic admin password"],
    ["Your authenticator or recovery code", "123456"],
  ])
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  fireEvent.click(screen.getByRole("button", { name: "Reset credentials" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});
