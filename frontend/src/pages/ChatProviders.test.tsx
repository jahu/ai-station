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
import ChatProviders from "./ChatProviders";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("never displays a secret value and submits a reference instead", async () => {
  const openai = {
    id: "new",
    key: "openai",
    name: "OpenAI",
    location: "external",
    endpoint: "https://api.example.test/v1",
    secret_ref: "env:OPENAI_API_KEY",
    secret_source: "env",
    secret_present: true,
    builtin: false,
    enabled: true,
  };
  const builtin = {
    id: "builtin-id",
    key: "local-openai-compatible",
    name: "Local OpenAI-compatible",
    location: "local",
    endpoint: "http://127.0.0.1:11434/v1",
    secret_ref: "",
    secret_source: "none",
    secret_present: false,
    builtin: true,
    enabled: true,
  };
  let created = false;
  const fetch = vi.fn(async (_path: string, options?: RequestInit) => {
    if (options?.method === "POST") created = true;
    return {
      ok: true,
      json: async () =>
        options?.method === "POST"
          ? openai
          : created
            ? [builtin, openai]
            : [builtin],
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
        <ChatProviders />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByText("Local OpenAI-compatible");
  expect(screen.getByText("No secret")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Name"), {
    target: { value: "OpenAI" },
  });
  fireEvent.change(screen.getByLabelText("Key"), {
    target: { value: "openai" },
  });
  fireEvent.change(screen.getByLabelText("Endpoint"), {
    target: { value: "https://api.example.test/v1" },
  });
  fireEvent.change(screen.getByLabelText("Secret reference"), {
    target: { value: "env:OPENAI_API_KEY" },
  });
  fireEvent.change(screen.getByLabelText("Store secret"), {
    target: { value: "sk-must-not-remain-visible" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Add provider" }));
  await waitFor(() =>
    expect(fetch.mock.calls.some((call) => call[1]?.method === "POST")).toBe(
      true,
    ),
  );
  const posted = fetch.mock.calls.find((call) => call[1]?.method === "POST");
  expect(posted?.[0]).toBe("/api/chat/providers");
  const body = String(posted?.[1]?.body);
  expect(body).toContain("sk-must-not-remain-visible");
  await screen.findByText("env:OPENAI_API_KEY");
  expect(screen.getByLabelText("Store secret")).toHaveProperty("value", "");
  expect(screen.queryByDisplayValue("sk-must-not-remain-visible")).toBeNull();
  expect(screen.queryByText("sk-must-not-remain-visible")).toBeNull();
});

it("moves through chat providers with arrow keys", async () => {
  const row = {
    location: "external",
    endpoint: "https://api.example.test/v1",
    secret_ref: "env:OPENAI_API_KEY",
    secret_source: "env",
    secret_present: true,
    builtin: false,
    enabled: true,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => [
        {
          ...row,
          id: "prov-one",
          key: "local-openai-compatible",
          name: "Local OpenAI-compatible",
          location: "local",
          endpoint: "http://127.0.0.1:11434/v1",
          secret_ref: "",
          secret_source: "none",
          secret_present: false,
          builtin: true,
        },
        {
          ...row,
          id: "prov-two",
          key: "openai",
          name: "OpenAI",
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
        <ChatProviders />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByText("Local OpenAI-compatible");
  const first = screen
    .getByText("Local OpenAI-compatible")
    .closest("[data-list-index]") as HTMLElement;
  const second = screen.getByRole("button", {
    name: "Remove OpenAI prov-two",
  });
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(screen.getByRole("region", { name: "Chat providers" })).toBeTruthy();
  expect(screen.getByText(/Chat provider list. Use arrow keys/)).toBeTruthy();
  fireEvent.keyDown(first.closest(".diagnostic-list") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  expect(document.activeElement).toBe(
    screen.getByText("OpenAI").closest("[data-list-index]"),
  );
  fireEvent.keyDown(second.closest(".diagnostic-list") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
});
