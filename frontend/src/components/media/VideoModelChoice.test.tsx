import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import VideoModelChoice from "./VideoModelChoice";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function mount(available: boolean) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({
        items: [
          {
            id: "recurrent-model",
            name: "SVI Pro",
            available,
            profile: "832×480 · 15 fps · 12 GiB GPU · 24 GiB RAM",
          },
        ],
      }),
    })),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <VideoModelChoice value="recurrent-model" onChange={vi.fn()} />
    </QueryClientProvider>,
  );
}

it("shows the selected model's actual profile instead of a hard-coded 5B resolution", async () => {
  mount(true);
  await screen.findByText(/832×480 · 15 fps/);
  expect(screen.queryByText(/1280 × 704/)).toBeNull();
  expect(
    (screen.getByRole("option", { name: "SVI Pro" }) as HTMLOptionElement)
      .disabled,
  ).toBe(false);
});

it("retains unavailable saved selections without allowing a new selection", async () => {
  mount(false);
  const option = await screen.findByRole("option", {
    name: "SVI Pro · unavailable",
  });
  expect((option as HTMLOptionElement).disabled).toBe(true);
  expect(
    (screen.getByRole("combobox", { name: "Video model" }) as HTMLSelectElement)
      .value,
  ).toBe("recurrent-model");
});
