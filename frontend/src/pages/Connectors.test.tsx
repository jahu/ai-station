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

it("moves through named connectors with arrow keys", async () => {
  const row = {
    key: "status-page",
    kind: "http",
    url: "https://www.example.com/status",
    method: "GET",
    status: "unconfigured",
    health: "unknown",
    enabled: true,
    secret_ref: "env:STATUS_TOKEN",
    secret_source: "env",
    secret_present: true,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => ({
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
          : [
              {
                ...row,
                id: "http-one",
                name: "Status page",
                last_run_id: "run-one",
              },
              {
                ...row,
                id: "http-two",
                name: "Docs feed",
                last_run_id: "run-two",
              },
            ],
    })),
  );
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
  const first = await screen.findByRole("link", {
    name: "Inspect Status page http-one",
  });
  const second = screen.getByRole("link", {
    name: "Inspect Docs feed http-two",
  });
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(screen.getByRole("region", { name: "Named connectors" })).toBeTruthy();
  expect(
    screen.getByRole("region", { name: "Unavailable adapters" }),
  ).toBeTruthy();
  expect(screen.getByText("Browser automation is not enabled.")).toBeTruthy();
  fireEvent.keyDown(first.closest(".diagnostic-list") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  expect(document.activeElement).toBe(
    screen.getByRole("link", { name: "Inspect Docs feed http-two" }).closest(
      "[data-list-index]",
    ),
  );
  fireEvent.keyDown(second.closest(".diagnostic-list") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
});

it("moves through unpublished adapters with arrow keys", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => ({
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
              {
                kind: "github",
                operational: false,
                summary: "GitHub connector is not enabled.",
              },
            ]
          : [],
    })),
  );
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
  const first = await screen.findByLabelText("Adapter browser");
  const second = screen.getByLabelText("Adapter github");
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(
    screen.getByRole("region", { name: "Unavailable adapters" }),
  ).toBeTruthy();
  expect(
    screen.getByText(/These kinds stay unavailable/),
  ).toBeTruthy();
  expect(screen.queryByRole("button", { name: /enable|publish/i })).toBeNull();
  fireEvent.keyDown(first.closest(".diagnostic-list") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  expect(document.activeElement).toBe(second);
  fireEvent.keyDown(second.closest(".diagnostic-list") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
});
