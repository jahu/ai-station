import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import LibraryPicker from "./LibraryPicker";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("excludes existing inputs and caps the remaining image selection", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () =>
        ["existing", "one", "two"].map((id) => ({
          id,
          original_filename: id,
          type: "image",
          mime_type: "image/png",
          metadata: {},
        })),
    })),
  );
  const select = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <LibraryPicker
        kind="image"
        existing={["existing"]}
        limit={1}
        busy={false}
        onSelect={select}
      />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Images from Library" }));
  expect(
    await screen.findByRole("dialog", { name: "Choose image references" }),
  ).toBeTruthy();
  expect(screen.getByLabelText("Search input Library")).toBeTruthy();
  expect(
    (await screen.findByRole("button", { name: "existing" })).hasAttribute(
      "disabled",
    ),
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "two" }));
  expect(
    screen.getByRole("button", { name: "one" }).hasAttribute("disabled"),
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Attach file" }));
  expect(select.mock.calls[0][0].map((a: { id: string }) => a.id)).toEqual([
    "two",
  ]);
});
