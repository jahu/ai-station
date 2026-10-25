import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { Run } from "../api";
import {
  ReportAlertEditor,
  ReportAlertField,
  ReportAlertResult,
} from "./AgentReportAlerts";
import { agentSettingsPayload } from "./agentSettings";

afterEach(cleanup);

it("lets an operator edit and explicitly save a criterion without applying each keystroke", () => {
  const save = vi.fn();
  render(<ReportAlertEditor tools={["web_search"]} value="" onSave={save} />);
  const field = screen.getByRole("textbox", {
    name: "Only notify when (optional)",
  });
  fireEvent.change(field, {
    target: { value: "A significant new model fits this station." },
  });
  expect(save).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "Save notification criterion" }),
  );
  expect(save).toHaveBeenCalledWith(
    "A significant new model fits this station.",
  );
});

it("preserves a saved criterion on unrelated edits and requires an explicit clear", () => {
  const agent = {
    name: "Watcher",
    updated_at: "2026-10-25T10:00:00Z",
    notification_policy: {
      on_success: true,
      on_failure: true,
      on_approval: false,
      report_condition: "Only significant new findings",
    },
  };
  expect(
    agentSettingsPayload(agent, { description: "Edited description" })
      .notification_policy,
  ).toEqual(agent.notification_policy);
  expect(
    agentSettingsPayload(agent, {
      notification_policy: {
        ...agent.notification_policy,
        report_condition: "",
      },
    }).notification_policy,
  ).toEqual({ on_success: true, on_failure: true, on_approval: false });
});

it("keeps an existing criterion visible when output changes instead of silently widening notifications", () => {
  const change = vi.fn();
  render(
    <ReportAlertField
      tools={["coding_local"]}
      value="Only new findings"
      onChange={change}
    />,
  );
  expect(screen.getByRole("alert").textContent).toContain("Explicitly clear");
  expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe(
    "Only new findings",
  );
  expect(change).not.toHaveBeenCalled();
});

function run(id: string, created_at: string, extra: Partial<Run> = {}): Run {
  return {
    id,
    created_at,
    executor_type: "agent",
    status: "succeeded",
    metadata: {
      report_alert: {
        state: "checked",
        notify: false,
        criterion: "Only new findings",
        reason: "The same release was already in the previous report.",
        previous_report: { run_id: "previous" },
      },
    },
    ...extra,
  } as Run;
}

it("shows the actual suppressed decision and an inspectable comparison without hiding the report", () => {
  render(
    <MemoryRouter>
      <ReportAlertResult runs={[run("current", "2026-10-25T10:00:00Z")]} />
    </MemoryRouter>,
  );
  expect(screen.getByRole("heading", { name: "No alert needed" })).toBeTruthy();
  expect(
    screen.getByText("No success notice or email was queued for this report."),
  ).toBeTruthy();
  expect(
    screen
      .getByRole("link", { name: "Compared with the previous report" })
      .getAttribute("href"),
  ).toBe("/runs/previous");
  expect(
    screen
      .getByRole("link", { name: "Inspect this report & alert check" })
      .getAttribute("href"),
  ).toBe("/runs/current");
});

it("does not reuse an older decision when the newest report has no completed check", () => {
  render(
    <MemoryRouter>
      <ReportAlertResult
        runs={[
          run("older", "2026-10-24T10:00:00Z"),
          run("newer", "2026-10-25T10:00:00Z", {
            status: "running",
            metadata: {},
          }),
        ]}
      />
    </MemoryRouter>,
  );
  expect(
    screen.queryByRole("region", { name: "Notification decision" }),
  ).toBeNull();
});

it("identifies an interrupted check rather than claiming a matching result", () => {
  render(
    <MemoryRouter>
      <ReportAlertResult
        runs={[
          run("current", "2026-10-25T10:00:00Z", {
            status: "interrupted",
            metadata: {
              report_alert: {
                state: "checking",
                criterion: "Only new findings",
              },
            },
          }),
        ]}
      />
    </MemoryRouter>,
  );
  expect(
    screen.getByRole("heading", { name: "Alert check needs attention" }),
  ).toBeTruthy();
  expect(screen.queryByText("Matching finding")).toBeNull();
});

it("offers the same reviewed criterion for data analysis", () => {
  render(
    <ReportAlertField
      tools={["python_data"]}
      value="Total exceeds 100"
      onChange={vi.fn()}
    />,
  );
  expect(screen.queryByRole("alert")).toBeNull();
  expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe(
    "Total exceeds 100",
  );
});

it("shows a failed data notification check independently of its successful analysis", () => {
  render(
    <MemoryRouter>
      <ReportAlertResult
        runs={[
          run("data", "2026-10-25T10:00:00Z", {
            executor_type: "agent_data_result",
            status: "succeeded",
            metadata: {
              report_alert: {
                state: "checking",
                criterion: "Total exceeds 100",
                check_run_id: "check",
              },
            },
          }),
          run("check", "2026-10-25T10:01:00Z", {
            executor_type: "agent_result_alert",
            status: "failed",
            metadata: {},
          }),
        ]}
      />
    </MemoryRouter>,
  );
  expect(
    screen.getByRole("heading", { name: "Alert check needs attention" }),
  ).toBeTruthy();
  expect(
    screen
      .getByRole("link", { name: "Inspect this report & alert check" })
      .getAttribute("href"),
  ).toBe("/runs/check");
  expect(
    screen.getByText(
      "The report remains available. No success notification has been sent.",
    ),
  ).toBeTruthy();
});
