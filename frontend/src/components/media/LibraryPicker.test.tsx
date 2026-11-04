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
    (await screen.findByRole("button", { name: /existing/ })).hasAttribute(
      "disabled",
    ),
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: /^Choose two / }));
  expect(
    screen
      .getByRole("button", { name: /^Choose one / })
      .hasAttribute("disabled"),
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Attach file" }));
  expect(select.mock.calls[0][0].map((a: { id: string }) => a.id)).toEqual([
    "two",
  ]);
});

it("moves through Library picker artifacts with arrow keys", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => [
        {
          id: "pick-one",
          original_filename: "alpha.png",
          type: "image",
          mime_type: "image/png",
          metadata: {},
        },
        {
          id: "pick-two",
          original_filename: "bravo.png",
          type: "image",
          mime_type: "image/png",
          metadata: {},
        },
      ],
    })),
  );
  render(
    <QueryClientProvider client={new QueryClient()}>
      <LibraryPicker
        kind="image"
        existing={[]}
        limit={4}
        busy={false}
        onSelect={vi.fn()}
      />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Images from Library" }));
  const first = await screen.findByRole("button", {
    name: "Choose alpha.png pick-one",
  });
  const second = screen.getByRole("button", {
    name: "Choose bravo.png pick-two",
  });
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(
    screen.getByRole("region", { name: "Reusable artifacts" }),
  ).toBeTruthy();
  fireEvent.keyDown(first.closest(".library-picker-grid") as HTMLElement, {
    key: "ArrowDown",
  });
  expect(second.tabIndex).toBe(0);
  expect(first.tabIndex).toBe(-1);
  expect(document.activeElement).toBe(second);
  fireEvent.keyDown(second.closest(".library-picker-grid") as HTMLElement, {
    key: "Home",
  });
  expect(first.tabIndex).toBe(0);
});

it("keeps voice references short WAVs while transcription can reuse other recordings", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => [
        {
          id: "short",
          type: "audio",
          mime_type: "audio/wav",
          original_filename: "voice.wav",
          metadata: { duration_seconds: 14 },
        },
        {
          id: "long",
          type: "audio",
          mime_type: "audio/wav",
          original_filename: "meeting.wav",
          metadata: { duration_seconds: 120 },
        },
        {
          id: "compressed",
          type: "audio",
          mime_type: "audio/mp4",
          original_filename: "meeting.m4a",
          metadata: {},
        },
      ],
    })),
  );
  const mount = (mode: "voice" | "transcription") =>
    render(
      <QueryClientProvider client={new QueryClient()}>
        <LibraryPicker
          kind="audio"
          audioMode={mode}
          existing={[]}
          limit={1}
          busy={false}
          onSelect={vi.fn()}
        />
      </QueryClientProvider>,
    );
  mount("voice");
  fireEvent.click(screen.getByRole("button", { name: "Voice from Library" }));
  await screen.findByRole("button", { name: "Choose voice.wav short" });
  expect(
    screen.queryByRole("button", { name: "Choose meeting.m4a compress" }),
  ).toBeNull();
  expect(
    screen.queryByRole("button", { name: "Choose meeting.wav long" }),
  ).toBeNull();
  cleanup();
  mount("transcription");
  fireEvent.click(
    screen.getByRole("button", { name: "Recordings from Library" }),
  );
  expect(
    await screen.findByRole("dialog", { name: "Choose a recording" }),
  ).toBeTruthy();
  expect(
    await screen.findByRole("button", {
      name: "Choose meeting.m4a compress",
    }),
  ).toBeTruthy();
  expect(
    screen.getByRole("button", { name: "Choose meeting.wav long" }),
  ).toBeTruthy();
});

it("retains ordered selections across pages and server searches", async () => {
  const image = (id: string) => ({
    id,
    original_filename: `${id}.png`,
    type: "image",
    mime_type: "image/png",
    metadata: {},
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => {
      const params = new URL(path, "http://localhost").searchParams;
      return {
        ok: true,
        json: async () =>
          params.get("search") === "favourite"
            ? [image("favourite")]
            : params.get("offset") === "40"
              ? [image("older")]
              : Array.from({ length: 40 }, (_, i) => image(`recent-${i}`)),
      };
    }),
  );
  const onSelect = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <LibraryPicker
        kind="image"
        existing={[]}
        limit={4}
        busy={false}
        onSelect={onSelect}
      />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Images from Library" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Choose recent-0.png recent-0" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Load more files" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Choose older.png older" }),
  );
  fireEvent.change(screen.getByLabelText("Search input Library"), {
    target: { value: "favourite" },
  });
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Choose favourite.png favourit",
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Attach 3 files" }));
  expect(onSelect.mock.calls[0][0].map((a: { id: string }) => a.id)).toEqual([
    "recent-0",
    "older",
    "favourite",
  ]);
});
