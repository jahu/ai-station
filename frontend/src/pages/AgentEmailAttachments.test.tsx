import { useState, type ReactElement } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import {
  ResultEmailSettings,
  ResultEmailApproval,
  type ResultEmailScope,
} from "./AgentResultEmail";
import { DeliveryPreview, type Delivery } from "./EmailConnectors";

const mail = {
  id: "mail",
  kind: "email",
  name: "Personal mail",
  enabled: true,
  email_policy_revision: "a".repeat(64),
  smtp: {
    sender: "station@example.com",
    allowed_recipients: ["one@example.com"],
  },
};
const base: ResultEmailScope = {
  connector_id: "mail",
  connector_revision: "a".repeat(64),
  recipients: ["one@example.com"],
  mode: "review",
  content: "summary",
  subject_prefix: "Station",
};
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function mount(element: ReactElement) {
  const fetch = vi.fn(async (_url: string, options?: RequestInit) => {
    expect(options?.method ?? "GET").toBe("GET");
    return { ok: true, json: async () => [mail] };
  });
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>{element}</MemoryRouter>
    </QueryClientProvider>,
  );
  return fetch;
}
it("offers generated formats only for data agents, with no hidden default selection or sending", async () => {
  const changed = vi.fn();
  function Settings() {
    const [value, setValue] = useState(base);
    return (
      <ResultEmailSettings
        value={value}
        dataFiles
        onChange={(next) => {
          if (next) {
            setValue(next);
            changed(next);
          }
        }}
      />
    );
  }
  const fetch = mount(<Settings />);
  fireEvent.click(screen.getByText(/Email delivery/));
  await screen.findByRole("option", { name: "Personal mail" });
  const excel = screen.getByRole("checkbox", {
    name: "Attach Excel workbook",
  }) as HTMLInputElement;
  expect(excel.checked).toBe(false);
  fireEvent.click(excel);
  fireEvent.click(screen.getByRole("checkbox", { name: "Attach CSV table" }));
  expect(changed.mock.calls.at(-1)?.[0].attachment_kinds).toEqual([
    "csv",
    "xlsx",
  ]);
  expect(screen.getByText("Result summary body")).toBeTruthy();
  fireEvent.click(screen.getByRole("checkbox", { name: "Attach CSV table" }));
  fireEvent.click(
    screen.getByRole("checkbox", { name: "Attach Excel workbook" }),
  );
  expect(changed.mock.calls.at(-1)?.[0].attachment_kinds).toBeUndefined();
  expect(fetch).toHaveBeenCalledTimes(1);
});
it("keeps attachment choices absent for ordinary report-only agents", async () => {
  mount(<ResultEmailSettings value={base} onChange={() => {}} />);
  fireEvent.click(screen.getByText(/Email delivery/));
  await screen.findByRole("option", { name: "Personal mail" });
  expect(
    screen.queryByRole("group", { name: "Generated file attachments" }),
  ).toBeNull();
});
it("shows that selected file data is included in automatic delivery consent", () => {
  mount(
    <ResultEmailApproval
      scope={{ ...base, mode: "automatic", attachment_kinds: ["xlsx"] }}
      enabled={false}
      checked={false}
      onChange={() => {}}
    />,
  );
  expect(
    screen.getByText(/Generated files will also leave this workstation/),
  ).toBeTruthy();
  expect(screen.getByText("Excel workbook")).toBeTruthy();
  expect(
    screen.queryByText(
      "Only completion status and result IDs will leave this workstation.",
    ),
  ).toBeNull();
});
it("shows the exact reviewed filenames and sizes without loading their contents", () => {
  const fetch = mount(
    <DeliveryPreview
      refresh={() => {}}
      delivery={
        {
          id: "delivery",
          state: "prepared",
          reason: "",
          accepted_recipients: [],
          refused_recipients: [],
          payload: {
            sender: "station@example.com",
            recipients: ["one@example.com"],
            subject: "Completed workbook",
            body: "Result ready",
            attachments: [
              {
                artifact_id: "result",
                filename: "result.xlsx",
                mime_type:
                  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                size_bytes: 2048,
                sha256: "a".repeat(64),
              },
            ],
          },
          run: { id: "send", status: "waiting_for_approval" },
        } as unknown as Delivery
      }
    />,
  );
  expect(
    screen
      .getByRole("link", { name: "Inspect attachment result.xlsx" })
      .getAttribute("href"),
  ).toBe("/library/result");
  expect(screen.getByText(/2 KiB/)).toBeTruthy();
  expect(fetch).not.toHaveBeenCalled();
});
