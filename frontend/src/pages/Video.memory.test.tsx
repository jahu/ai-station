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
import Video from "./Video";
import VideoMemoryProfile from "../components/media/VideoMemoryProfile";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

function mount(available: boolean, saved = false) {
  const writes: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") writes.push(JSON.parse(String(init.body)));
      return {
        ok: true,
        json: async () =>
          url.endsWith("/capabilities")
            ? {
                available: true,
                memory_profiles: [{ id: "bounded_11g", available }],
              }
            : url.endsWith("/hardware")
              ? { gpus: [] }
              : url.includes("/runs/") || init?.method === "POST"
                ? { id: "run", status: "queued", parameters: {} }
                : [],
      };
    }),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        {saved ? (
          <VideoMemoryProfile value="bounded_11g" onChange={() => {}} />
        ) : (
          <Video />
        )}
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return writes;
}

it("does not offer an unqualified or disabled memory profile", async () => {
  mount(false);
  await screen.findByText("Wan 2.2 · Local");
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Generate video" })).toBeTruthy(),
  );
  expect(screen.queryByLabelText("Video generation profile")).toBeNull();
});

it("chooses compatible settings and submits the reviewed reduced profile", async () => {
  const writes = mount(true);
  const selector = await screen.findByLabelText("Video generation profile");
  fireEvent.change(screen.getByLabelText("Format"), {
    target: { value: "704x1280" },
  });
  fireEvent.change(selector, { target: { value: "bounded_11g" } });
  expect((screen.getByLabelText("Format") as HTMLSelectElement).value).toBe(
    "1280x704",
  );
  expect((screen.getByLabelText("Format") as HTMLSelectElement).disabled).toBe(
    true,
  );
  fireEvent.change(screen.getByLabelText("Scene and motion"), {
    target: { value: "Coast at dawn" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Generate video" }));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0]).toMatchObject({
    memory_profile: "bounded_11g",
    width: 1280,
    height: 704,
    steps: 20,
  });
});

it("preserves a saved unavailable choice and gives a clear recovery action", async () => {
  mount(false, true);
  await screen.findByText(/saved profile is currently unavailable/);
  expect(
    (screen.getByLabelText("Video generation profile") as HTMLSelectElement)
      .value,
  ).toBe("bounded_11g");
  expect(screen.getByRole("option", { name: "Standard" })).toBeTruthy();
});
