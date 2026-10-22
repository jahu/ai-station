import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { EmailConnectors, type EmailConnector } from "./EmailConnectors";

const row: EmailConnector = {
  id: "mail-one",
  key: "mail",
  name: "My mailbox",
  smtp: {
    host: "smtp.example.com",
    sender: "station@example.com",
    username: "station",
    transport: "ssl",
    allowed_recipients: ["one@example.com", "two@example.com"],
  },
  enabled: true,
  health: "unknown",
  status: "unconfigured",
  secret_present: true,
  updated_at: "2026-10-22T12:00:00Z",
  last_run_id: null,
};
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function mount(rows: EmailConnector[] = [row], initial: unknown[] = []) {
  const calls: { path: string; body: Record<string, unknown> }[] = [];
  let history = initial;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      if (
        init?.method === "POST" ||
        init?.method === "PATCH" ||
        init?.method === "DELETE"
      ) {
        const body = init.body ? JSON.parse(String(init.body)) : {};
        calls.push({ path, body });
        if (path.endsWith("/drafts"))
          history = [
            {
              id: "draft-one",
              state: "prepared",
              reason: "",
              payload: {
                sender: row.smtp.sender,
                recipients: body.recipients,
                subject: body.subject,
                body: body.body,
              },
              accepted_recipients: [],
              refused_recipients: [],
              run: { id: "run-one", status: "waiting_for_approval" },
            },
          ];
        return { ok: true, json: async () => ({ id: "operation" }) };
      }
      return { ok: true, json: async () => history };
    }),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <EmailConnectors rows={rows} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return calls;
}

it("saves typed SMTP settings and a write-only credential without sending or checking", async () => {
  const calls = mount([]);
  fireEvent.click(screen.getByRole("button", { name: "Connect email" }));
  fireEvent.change(screen.getByLabelText("Sender address"), {
    target: { value: "station@example.com" },
  });
  fireEvent.change(screen.getByLabelText("SMTP server"), {
    target: { value: "smtp.example.com" },
  });
  fireEvent.change(screen.getByLabelText("Username"), {
    target: { value: "station" },
  });
  const password = screen.getByLabelText("App password") as HTMLInputElement;
  expect(password.type).toBe("password");
  fireEvent.change(password, { target: { value: "synthetic-secret" } });
  fireEvent.change(screen.getByLabelText("Allowed recipients"), {
    target: { value: "one@example.com\ntwo@example.com" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Save email connection" }),
  );
  await waitFor(() => expect(calls).toHaveLength(1));
  expect(calls[0].path).toBe("/api/connectors");
  expect(calls[0].body).toMatchObject({
    kind: "email",
    secret: "synthetic-secret",
    smtp: {
      transport: "ssl",
      allowed_recipients: ["one@example.com", "two@example.com"],
    },
  });
});

it("prepares an immutable preview and needs a separate explicit approval to send", async () => {
  const calls = mount();
  fireEvent.click(screen.getByRole("button", { name: "Prepare a message" }));
  fireEvent.change(screen.getByLabelText("Subject"), {
    target: { value: "Reviewed subject" },
  });
  fireEvent.change(screen.getByLabelText("Message"), {
    target: { value: "Reviewed body" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Prepare preview" }));
  await screen.findByRole("button", { name: "Approve and send" });
  expect(calls).toHaveLength(1);
  expect(calls[0].path).toBe("/api/email/connectors/mail-one/drafts");
  expect(calls[0].body).toMatchObject({
    recipients: ["one@example.com"],
    subject: "Reviewed subject",
    body: "Reviewed body",
    expected_updated_at: row.updated_at,
  });
  expect(screen.getByText("Reviewed body")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Approve and send" }));
  await waitFor(() => expect(calls).toHaveLength(2));
  expect(calls[1]).toEqual({
    path: "/api/runs/run-one/approval",
    body: { resolution: "granted" },
  });
});

it("keeps unknown acceptance visible and does not offer a blind retry", async () => {
  mount(
    [row],
    [
      {
        id: "old",
        state: "unknown",
        reason: "Inspect the mail server before preparing another message.",
        payload: {
          sender: row.smtp.sender,
          recipients: ["one@example.com"],
          subject: "Uncertain message",
          body: "Frozen content",
        },
        accepted_recipients: [],
        refused_recipients: [],
        run: { id: "run-old", status: "interrupted" },
      },
    ],
  );
  await screen.findByText(/Acceptance unknown/);
  expect(screen.getByText("Frozen content")).toBeTruthy();
  expect(screen.queryByRole("button", { name: /retry/i })).toBeNull();
  expect(screen.queryByRole("button", { name: "Approve and send" })).toBeNull();
});

it("does not reveal a saved password when editing and preserves it on unrelated saves", async () => {
  const calls = mount();
  fireEvent.click(screen.getByRole("button", { name: "Mail settings" }));
  expect(
    (screen.getByLabelText("Replace password (optional)") as HTMLInputElement)
      .value,
  ).toBe("");
  fireEvent.change(screen.getByLabelText("Name"), {
    target: { value: "A better name" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save mail settings" }));
  await waitFor(() => expect(calls).toHaveLength(1));
  expect(calls[0].body.expected_updated_at).toBe(row.updated_at);
  expect(calls[0].body).not.toHaveProperty("secret");
});

it("requires confirmation before removing a connection and preserves history in the prompt", async () => {
  const calls = mount();
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  fireEvent.click(screen.getByRole("button", { name: "Remove connection" }));
  expect(calls).toHaveLength(0);
  expect(confirm).toHaveBeenCalledWith(
    expect.stringContaining("Delivery history is preserved"),
  );
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: "Remove connection" }));
  await waitFor(() => expect(calls).toHaveLength(1));
  expect(calls[0].path).toBe("/api/connectors/mail-one");
  confirm.mockRestore();
});

it("keeps checking and sending disabled when a saved connection is disabled", () => {
  mount([{ ...row, enabled: false, health: "healthy" }]);
  expect(screen.getByText("Disabled")).toBeTruthy();
  expect(
    screen
      .getByRole("button", { name: "Check connection" })
      .matches(":disabled"),
  ).toBe(true);
  expect(
    screen
      .getByRole("button", { name: "Prepare a message" })
      .matches(":disabled"),
  ).toBe(true);
});
