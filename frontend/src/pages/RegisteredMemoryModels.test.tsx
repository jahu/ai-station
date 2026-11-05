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
import RegisteredMemoryModels from "./RegisteredMemoryModels";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function mount(canSelect = true, available = true) {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={["/memory?embedding_model=new-encoder"]}>
        <RegisteredMemoryModels
          models={[
            {
              id: "new-encoder",
              name: "My encoder",
              available,
              device: "CPU",
              dimension: 384,
            },
          ]}
          revision={7}
          canSelect={canSelect}
          busy={false}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
it("opens an installed model without changing memory until the explicit action", async () => {
  const fetch = vi.fn(async () => ({ ok: true, json: async () => ({}) }));
  vi.stubGlobal("fetch", fetch);
  mount();
  expect(
    (screen.getByLabelText("Memory model") as HTMLSelectElement).value,
  ).toBe("new-encoder");
  expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Use for memory" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  const [path, options] = fetch.mock.calls[0] as unknown as [
    string,
    RequestInit,
  ];
  expect(path).toBe("/api/memory/embeddings/models/new-encoder/select");
  expect(JSON.parse(String(options.body))).toEqual({
    expected_revision: 7,
    confirm: true,
  });
});
it("allows members to inspect the choice while preventing station configuration changes", () => {
  mount(false);
  expect(
    (
      screen.getByRole("button", {
        name: "Use for memory",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(screen.getByText(/An administrator can change/)).toBeTruthy();
});
it("preserves an unavailable installed choice and prevents selection", () => {
  mount(true, false);
  expect(
    (
      screen.getByRole("button", {
        name: "Use for memory",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(screen.getByText(/My encoder.*unavailable/)).toBeTruthy();
});
