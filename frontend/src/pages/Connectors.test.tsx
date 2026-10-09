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
import Connectors from "./Connectors";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("never displays a secret value and keeps unavailable kinds unpublished", async () => {
  const row = {
    id: "http-1",
    key: "status-page",
    name: "Status page",
    kind: "http",
    url: "https://www.example.com/status",
    method: "GET",
    status: "unconfigured",
    health: "unknown",
    enabled: true,
    last_run_id: null,
    secret_ref: "env:STATUS_TOKEN",
    secret_source: "env",
    secret_present: true,
  };
  let created = false;
  const fetch = vi.fn(async (path: string, options?: RequestInit) => {
    if (options?.method === "POST" && String(path).endsWith("/connectors"))
      created = true;
    return {
      ok: true,
      json: async () =>
        String(path).endsWith("/kinds")
          ? [
              { kind: "http", operational: true, summary: "GET" },
              {
                kind: "browser",
                operational: false,
                summary: "Browser automation is not enabled.",
              },
            ]
          : options?.method === "POST"
            ? row
            : created
              ? [row]
              : [],
    };
  });
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <Connectors />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(
    await screen.findByText("Browser automation is not enabled."),
  ).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Name"), {
    target: { value: "Status page" },
  });
  fireEvent.change(screen.getByLabelText("Key"), {
    target: { value: "status-page" },
  });
  fireEvent.change(screen.getByLabelText("Public URL"), {
    target: { value: "https://www.example.com/status" },
  });
  fireEvent.change(screen.getByLabelText("Secret reference"), {
    target: { value: "env:STATUS_TOKEN" },
  });
  fireEvent.change(screen.getByLabelText("Store secret"), {
    target: { value: "sk-should-not-appear" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Add connector" }));
  await waitFor(() => expect(created).toBe(true));
  const posted = fetch.mock.calls.find((call) => call[1]?.method === "POST");
  expect(posted?.[0]).toBe("/api/connectors");
  const body = String(posted?.[1]?.body);
  expect(body).toContain("sk-should-not-appear");
  await screen.findByText("env:STATUS_TOKEN");
  expect(screen.getByLabelText("Store secret")).toHaveProperty("value", "");
  expect(screen.queryByDisplayValue("sk-should-not-appear")).toBeNull();
  expect(screen.queryByText("sk-should-not-appear")).toBeNull();
});
