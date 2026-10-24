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

function mount(available: boolean, saved = false, recommended = "default") {
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
                recommended_memory_profile: recommended,
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

it("preselects a visible recommendation and freezes it on Send", async () => {
  const writes = mount(true, false, "bounded_11g");
  await screen.findByText(/Selected for the currently available memory/);
  expect(
    (screen.getByLabelText("Video generation profile") as HTMLSelectElement)
      .value,
  ).toBe("bounded_11g");
  fireEvent.change(screen.getByLabelText("Scene and motion"), {
    target: { value: "Coast at dawn" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Generate video" }));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0].memory_profile).toBe("bounded_11g");
});

it("honors a manual Standard override of the recommendation", async () => {
  const writes = mount(true, false, "bounded_11g");
  await screen.findByText(/Selected for the currently available memory/);
  fireEvent.change(screen.getByLabelText("Video generation profile"), {
    target: { value: "default" },
  });
  expect((screen.getByLabelText("Format") as HTMLSelectElement).disabled).toBe(
    false,
  );
  fireEvent.change(screen.getByLabelText("Scene and motion"), {
    target: { value: "Coast at dawn" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Generate video" }));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0]).not.toHaveProperty("memory_profile");
});

it("does not silently apply the text-only recommendation to image animation", async () => {
  mount(true, false, "bounded_11g");
  await screen.findByText(/Selected for the currently available memory/);
  fireEvent.click(screen.getByRole("radio", { name: "Animate an image" }));
  expect(
    (screen.getByLabelText("Video generation profile") as HTMLSelectElement)
      .value,
  ).toBe("default");
  expect((screen.getByLabelText("Format") as HTMLSelectElement).disabled).toBe(
    false,
  );
});

it("lets a new format override an automatic landscape recommendation", async () => {
  mount(true, false, "bounded_11g");
  await screen.findByText(/Selected for the currently available memory/);
  const format = screen.getByLabelText("Format") as HTMLSelectElement;
  expect(format.disabled).toBe(false);
  fireEvent.change(format, { target: { value: "704x1280" } });
  expect(format.value).toBe("704x1280");
  expect(
    (screen.getByLabelText("Video generation profile") as HTMLSelectElement)
      .value,
  ).toBe("default");
});
