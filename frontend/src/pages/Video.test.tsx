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

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function mount(entry = "/video", available = true) {
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      path.endsWith("/capabilities")
        ? { available, reason: "Configure installed models" }
        : path.endsWith("/hardware")
          ? { gpus: [] }
          : path.includes("/artifacts/")
            ? {
                id: "source",
                type: "image",
                mime_type: "image/png",
                original_filename: "scene.png",
              }
            : path.includes("/runs")
              ? { id: "video-run", status: "queued", parameters: {} }
              : [],
  }));
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={[entry]}>
        <Video />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return fetch;
}
it("queues text video with visible progress and Stop in place", async () => {
  const fetch = mount();
  await waitFor(() => expect(fetch).toHaveBeenCalled());
  fireEvent.change(screen.getByLabelText("Scene and motion"), {
    target: { value: "Mist drifts through a forest" },
  });
  await waitFor(() =>
    expect(
      screen
        .getByRole("button", { name: "Generate video" })
        .hasAttribute("disabled"),
    ).toBe(false),
  );
  fireEvent.click(screen.getByRole("button", { name: "Generate video" }));
  await screen.findByRole("button", { name: "Stop generation" });
  const call = fetch.mock.calls.find(([path]) => path === "/api/video/runs");
  expect(call).toBeTruthy();
  expect(
    screen
      .getByRole("button", { name: "Talking avatar" })
      .hasAttribute("disabled"),
  ).toBe(true);
  expect(
    screen.queryByText("A portrait. A voice. A living moment."),
  ).toBeNull();
});
it("stages Library first frame without starting work", async () => {
  const fetch = mount("/video?input=source");
  await screen.findByText("scene.png");
  expect(
    (
      screen.getByRole("radio", {
        name: "Animate an image",
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
  expect(fetch.mock.calls.some(([path]) => path === "/api/video/runs")).toBe(
    false,
  );
});
it("keeps unavailable setup honest and generation disabled", async () => {
  mount("/video", false);
  await screen.findByText(/Local video needs setup/);
  expect(
    screen
      .getByRole("button", { name: "Generate video" })
      .hasAttribute("disabled"),
  ).toBe(true);
});
it("preserves portrait and voice workflow as a separate mode", async () => {
  mount("/video?mode=avatar");
  expect(
    screen.getByRole("heading", { name: "Create avatar video" }),
  ).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Generate video" })).toBeNull();
});

it("does not submit animation without a first frame through the form", async () => {
  const fetch = mount();
  await screen.findByRole("radio", { name: "Animate an image" });
  fireEvent.click(screen.getByRole("radio", { name: "Animate an image" }));
  fireEvent.change(screen.getByLabelText("Scene and motion"), {
    target: { value: "Move the camera" },
  });
  fireEvent.submit(
    screen.getByRole("button", { name: "Generate video" }).closest("form")!,
  );
  expect(fetch.mock.calls.some(([path]) => path === "/api/video/runs")).toBe(
    false,
  );
});
