import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { Memory } from "./Memory";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("keeps embeddings off until an explicit local setup is saved", async () => {
  let setup = {
    configured: false,
    endpoint: "",
    model: "",
    dimension: null as number | null,
    indexed_count: 0,
    memory_count: 0,
    last_health_run_id: null as string | null,
    last_index_run_id: null as string | null,
  };
  const fetch = vi.fn(async (url: string, options?: RequestInit) => ({
    ok: true,
    json: async () => {
      if (String(url).includes("/embeddings/setup") && options?.method === "PUT") {
        const body = JSON.parse(String(options.body));
        setup = body.clear
          ? { ...setup, configured: false, endpoint: "", model: "" }
          : {
              ...setup,
              configured: true,
              endpoint: body.endpoint,
              model: body.model,
            };
        return setup;
      }
      if (String(url).includes("/embeddings/setup")) {
        return setup;
      }
      return [];
    },
  }));
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <Memory />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByText(/Embeddings are not configured/)).toBeTruthy();
  expect(
    (screen.getByRole("button", { name: "Check endpoint" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  fireEvent.change(screen.getByLabelText("Local embeddings base URL"), {
    target: { value: "http://127.0.0.1:11434/v1" },
  });
  fireEvent.change(
    screen.getByLabelText("Model name already served by that endpoint"),
    { target: { value: "nomic-embed-text" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "Save local setup" }));
  await screen.findByText(/Using nomic-embed-text at http:\/\/127.0.0.1:11434\/v1/);
  expect(
    fetch.mock.calls.some(
      (call) =>
        String(call[0]) === "/api/memory/embeddings/setup" &&
        call[1]?.method === "PUT" &&
        String(call[1].body).includes("nomic-embed-text"),
    ),
  ).toBe(true);
});
