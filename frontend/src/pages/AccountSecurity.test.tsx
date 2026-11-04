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
import AccountSecurity from "./AccountSecurity";

const qr = vi.hoisted(() =>
  vi.fn(async () => "data:image/png;base64,c3ludGhldGlj"),
);
vi.mock("qrcode", () => ({ default: { toDataURL: qr } }));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  qr.mockClear();
});
const user: AccountUser = {
  id: "alice",
  username: "Alice",
  display_name: "Alice",
  is_admin: false,
  enabled: true,
  mfa_enabled: false,
  created_at: "2026-10-30T00:00:00Z",
};
const reply = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
function mount(
  fetch: ReturnType<typeof vi.fn>,
  signOut = vi.fn(async () => {}),
) {
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <AccountContext.Provider value={{ mode: "accounts", user, signOut }}>
        <AccountSecurity />
      </AccountContext.Provider>
    </QueryClientProvider>,
  );
  return signOut;
}
it("renders enrollment QR locally and shows recovery codes only until acknowledged", async () => {
  const uri =
    "otpauth://totp/AIStation:Alice?secret=SYNTHETIC&issuer=AIStation";
  const fetch = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/account/mfa/enroll") {
      expect(JSON.parse(String(options?.body))).toEqual({
        password: "synthetic password",
      });
      return reply({
        provisioning_uri: uri,
        secret: "SYNTHETIC",
        expires_at: "2026-10-30T00:10:00Z",
      });
    }
    if (path === "/api/account/mfa/confirm")
      return reply({
        recovery_codes: ["synthetic-recovery-one", "synthetic-recovery-two"],
      });
    return reply([]);
  });
  mount(fetch);
  fireEvent.change(screen.getByLabelText("Password for two-factor settings"), {
    target: { value: "synthetic password" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Set up authenticator" }));
  const image = await screen.findByRole("img", {
    name: "Authenticator setup QR code",
  });
  expect(image.getAttribute("src")).toMatch(/^data:image/);
  expect(qr).toHaveBeenCalledWith(uri, { width: 192, margin: 2 });
  fireEvent.change(screen.getByLabelText("Authenticator code"), {
    target: { value: "123456" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Confirm and enable 2FA" }),
  );
  await screen.findByText("synthetic-recovery-one");
  expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toContain(
    "synthetic-recovery",
  );
  fireEvent.click(screen.getByRole("button", { name: "I saved these codes" }));
  expect(screen.queryByText("synthetic-recovery-one")).toBeNull();
  expect(fetch.mock.calls.every(([path]) => path.startsWith("/api/"))).toBe(
    true,
  );
});
it("changing the password ends the current account session only after success", async () => {
  const fetch = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/account/password") {
      expect(JSON.parse(String(options?.body))).toEqual({
        password: "synthetic old password",
        new_password: "synthetic new password",
      });
      return reply({ authenticated: false });
    }
    return reply([]);
  });
  const signOut = mount(fetch);
  for (const [label, value] of [
    ["Current password", "synthetic old password"],
    ["New password", "synthetic new password"],
    ["Confirm new password", "synthetic new password"],
  ])
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  fireEvent.click(
    screen.getByRole("button", { name: "Update password and sign out" }),
  );
  await waitFor(() => expect(signOut).toHaveBeenCalledTimes(1));
});
it("signing out another device does not sign out the current browser", async () => {
  const fetch = vi.fn(async (path: string, options?: RequestInit) => {
    if (options?.method === "DELETE") {
      expect(path).toBe("/api/account/devices/phone");
      return reply({ revoked: true });
    }
    return reply([
      {
        id: "phone",
        label: "iPhone",
        current: false,
        created_at: "2026-10-30T00:00:00Z",
        last_seen_at: "2026-10-30T00:00:00Z",
        expires_at: "2026-10-30T12:00:00Z",
      },
    ]);
  });
  const signOut = mount(fetch);
  fireEvent.click(
    await screen.findByRole("button", { name: "Sign out iPhone" }),
  );
  await waitFor(() =>
    expect(
      fetch.mock.calls.some(([, options]) => options?.method === "DELETE"),
    ).toBe(true),
  );
  expect(signOut).not.toHaveBeenCalled();
});
