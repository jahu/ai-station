import { useState, type ReactElement } from "react";
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
import {
  ResultEmailSettings,
  ResultEmailApproval,
  type ResultEmailScope,
} from "./AgentResultEmail";
import { resultEmailConsentKey, agentSettingsPayload } from "./agentSettings";
import { AgentMarketEmailHistory } from "./AgentMarketEmail";
import type { Run } from "../api";
import { AssistantAgentDraft } from "./AssistantAgentDraft";

const connection = {
  id: "mail",
  name: "Personal email",
  kind: "email",
  enabled: true,
  email_policy_revision: "a".repeat(64),
  smtp: {
    sender: "station@example.com",
    allowed_recipients: ["one@example.com", "two@example.com"],
  },
};
const scope: ResultEmailScope = {
  connector_id: "mail",
  connector_revision: "a".repeat(64),
  recipients: ["one@example.com"],
  mode: "review",
  content: "report",
  subject_prefix: "AI Station",
};
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function mount(element: ReactElement) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>{element}</MemoryRouter>
    </QueryClientProvider>,
  );
}
function fetchAccounts() {
  const fetch = vi.fn(async (url: string, options?: RequestInit) => {
    expect(url).toBe("/api/connectors");
    expect(options?.method).toBeUndefined();
    return { ok: true, json: async () => [connection] };
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}
function Settings({ summaryOnly = false }: { summaryOnly?: boolean }) {
  const [value, setValue] = useState<ResultEmailScope | null>(null);
  return (
    <ResultEmailSettings
      value={value}
      onChange={setValue}
      summaryOnly={summaryOnly}
    />
  );
}

it("keeps mail optional and lazy, then defaults to review with one saved recipient", async () => {
  const fetch = fetchAccounts();
  mount(<Settings />);
  expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Email delivery · AI Station only"));
  await screen.findByRole("option", { name: "Personal email" });
  fireEvent.change(screen.getByLabelText("Deliver results to"), {
    target: { value: "mail" },
  });
  expect(
    (screen.getByLabelText("Sending mode") as HTMLSelectElement).value,
  ).toBe("review");
  expect(
    (screen.getByLabelText("one@example.com") as HTMLInputElement).checked,
  ).toBe(true);
  expect(
    (screen.getByLabelText("one@example.com") as HTMLInputElement).disabled,
  ).toBe(true);
  fireEvent.click(screen.getByLabelText("two@example.com"));
  expect(
    (screen.getByLabelText("one@example.com") as HTMLInputElement).disabled,
  ).toBe(false);
  expect(screen.queryByRole("textbox", { name: /recipient/i })).toBeNull();
  expect(
    fetch.mock.calls.every((call) => call.length === 1 || !call[1]?.method),
  ).toBe(true);
});

it("uses a metadata summary for code and media with report text unavailable", async () => {
  fetchAccounts();
  mount(<Settings summaryOnly />);
  fireEvent.click(screen.getByText("Email delivery · AI Station only"));
  await screen.findByRole("option", { name: "Personal email" });
  fireEvent.change(screen.getByLabelText("Deliver results to"), {
    target: { value: "mail" },
  });
  expect(
    (screen.getByLabelText("Email content") as HTMLSelectElement).value,
  ).toBe("summary");
  expect(
    (
      screen.getByRole("option", {
        name: "Completed report text",
      }) as HTMLOptionElement
    ).disabled,
  ).toBe(true);
});

it("requires reviewing changed mail settings and never grants consent from choosing automatic", async () => {
  fetchAccounts();
  const change = vi.fn();
  mount(
    <ResultEmailSettings
      value={{
        ...scope,
        mode: "automatic",
        connector_revision: "b".repeat(64),
      }}
      onChange={change}
    />,
  );
  fireEvent.click(screen.getByText("Email delivery · Automatic"));
  const refresh = await screen.findByRole("button", {
    name: "Use current mail settings",
  });
  expect(screen.queryByLabelText("one@example.com")).toBeNull();
  fireEvent.click(refresh);
  expect(change).toHaveBeenCalledWith({ ...scope, mode: "automatic" });
  expect(
    screen.queryByRole("checkbox", { name: /I allow automatic/ }),
  ).toBeNull();
});

it("discloses full report scope and binds the unchecked consent to the saved definition version", () => {
  const changed = vi.fn();
  const { rerender } = mount(
    <ResultEmailApproval
      scope={{ ...scope, mode: "automatic" }}
      enabled={false}
      checked={false}
      onChange={changed}
    />,
  );
  const checkbox = screen.getByRole("checkbox", {
    name: /I allow automatic delivery/,
  }) as HTMLInputElement;
  expect(checkbox.checked).toBe(false);
  expect(screen.getByText(/actual completed report text/)).toBeTruthy();
  fireEvent.click(checkbox);
  expect(changed).toHaveBeenCalledWith(true);
  expect(resultEmailConsentKey({ id: "agent", updated_at: "old" })).not.toBe(
    resultEmailConsentKey({ id: "agent", updated_at: "new" }),
  );
  rerender(
    <ResultEmailApproval
      scope={scope}
      enabled={false}
      checked={false}
      onChange={changed}
    />,
  );
  expect(screen.queryByRole("checkbox")).toBeNull();
  expect(screen.getByText(/Every finished message waits/)).toBeTruthy();
});

it("preserves result delivery while changing notices and other settings, and omits it for legacy agents", () => {
  const agent = {
    name: "Report",
    updated_at: "now",
    notification_policy: { report_email: scope },
  };
  expect(
    agentSettingsPayload(agent, { model: "local" }).notification_policy
      .report_email,
  ).toEqual(scope);
  expect(
    agentSettingsPayload(agent, { notification_policy: { on_success: true } })
      .notification_policy.report_email,
  ).toEqual(scope);
  expect(
    agentSettingsPayload(agent, { notification_policy: { report_email: null } })
      .notification_policy.report_email,
  ).toBeNull();
  expect(
    agentSettingsPayload({ name: "Legacy", updated_at: "now" })
      .notification_policy,
  ).not.toHaveProperty("report_email");
});

it("shows the whole frozen email with real approval controls and a separate preparation failure", async () => {
  const calls = vi.fn(async (_url: string, options?: RequestInit) => ({
    ok: true,
    json: async () =>
      options
        ? {}
        : [
            {
              id: "delivery",
              state: "prepared",
              reason: "",
              payload: {
                sender: "station@example.com",
                recipients: ["one@example.com"],
                subject: "Actual report",
                body: "Actual complete report text.",
              },
              accepted_recipients: [],
              refused_recipients: [],
              run: { id: "email-run", status: "waiting_for_approval" },
            },
          ],
  }));
  vi.stubGlobal("fetch", calls);
  mount(
    <AgentMarketEmailHistory
      agentId="agent"
      title="Result email"
      runs={[
        {
          id: "source",
          metadata: { result_email: { state: "preparation_failed" } },
        } as unknown as Run,
      ]}
    />,
  );
  await screen.findByText("Actual complete report text.");
  expect(
    screen.getByText(/result is ready, but its email could not be prepared/),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Approve and send" }));
  await waitFor(() =>
    expect(
      calls.mock.calls.some(
        ([url, options]) =>
          url === "/api/runs/email-run/approval" &&
          JSON.parse(options!.body as string).resolution === "granted",
      ),
    ).toBe(true),
  );
});

it("keeps Run now available in a compact conversation after automatic delivery was approved", async () => {
  const agent = {
    id: "agent-one",
    name: "Daily report",
    goal: "Summarize observations",
    updated_at: "now",
    enabled: true,
    model: "fixture",
    tools: ["memory_search"],
    runs: [],
    notification_policy: { report_email: { ...scope, mode: "automatic" } },
    report_email_authorization: { valid: true, ready: true, mode: "automatic" },
  };
  const fetch = vi.fn(async (url: string, options?: RequestInit) => ({
    ok: true,
    json: async () => {
      if (options?.method === "POST") return { id: "queued" };
      if (url.includes("/agents/agent-one")) return agent;
      if (url.endsWith("/llama")) return { models: [], instances: [] };
      if (url.includes("/chat/provider"))
        return { models: ["fixture"], default_model: "fixture" };
      return [];
    },
  }));
  vi.stubGlobal("fetch", fetch);
  mount(<AssistantAgentDraft agentId={agent.id} compact />);
  const run = await screen.findByRole("button", {
    name: "Run now",
  });
  expect((run as HTMLButtonElement).disabled).toBe(false);
  fireEvent.click(run);
  await waitFor(() =>
    expect(
      fetch.mock.calls.some(
        ([url, options]) =>
          url === "/api/agents/agent-one/run" && options?.method === "POST",
      ),
    ).toBe(true),
  );
});

it.each([false, true])(
  "shows result-mail review without pretending report execution has not started (compact=%s)",
  async (compact) => {
    const agent = {
      id: "agent-one",
      name: "Daily report",
      goal: "Summarize observations",
      updated_at: "now",
      enabled: true,
      model: "fixture",
      tools: ["memory_search"],
      runs: [
        {
          id: "mail-run",
          executor_type: "email_send",
          status: "waiting_for_approval",
          capability: "email.send",
          parameters: { agent_result: { source_run_id: "report" } },
        },
      ],
      notification_policy: { report_email: scope },
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => ({
        ok: true,
        json: async () => {
          if (url.includes("/agents/agent-one")) return agent;
          if (url.includes("/email/deliveries"))
            return [
              {
                id: "delivery",
                state: "prepared",
                reason: "",
                payload: {
                  sender: "station@example.com",
                  recipients: scope.recipients,
                  subject: "Daily report",
                  body: "Actual report to review.",
                },
                accepted_recipients: [],
                refused_recipients: [],
                run: agent.runs[0],
              },
            ];
          if (url.endsWith("/llama")) return { models: [], instances: [] };
          if (url.includes("/chat/provider"))
            return { models: ["fixture"], default_model: "fixture" };
          return [];
        },
      })),
    );
    mount(<AssistantAgentDraft agentId={agent.id} compact={compact} />);
    await screen.findByText("Actual report to review.");
    expect(
      screen.queryByText(/tools and inference have not started/),
    ).toBeNull();
    expect(
      screen.getByRole("button", { name: "Approve and send" }),
    ).toBeTruthy();
    expect(
      compact
        ? screen.getByRole("button", { name: "Edit in conversation" })
        : screen.getByText("Open in Agents"),
    ).toBeTruthy();
  },
);
