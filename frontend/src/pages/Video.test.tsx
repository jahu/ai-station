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
function mount(
  entry = "/video",
  available = true,
  models: { id: string; name: string; available: boolean }[] = [],
  portrait = false,
  recurrent = false,
) {
  const fetch = vi.fn(async (path: string, options?: RequestInit) => ({
    ok: true,
    json: async () =>
      path.endsWith("/video/models")
        ? { items: models }
        : path.endsWith("/capabilities")
          ? {
              available,
              reason: "Configure installed models",
              ...(path.includes("/video/models/")
                ? {
                    configuration_source: "managed",
                    ...(recurrent
                      ? {
                          operation_recipe: {
                            label: "Wan 2.2 SVI Pro",
                            width: 832,
                            height: 480,
                            frames: 81,
                            fps: 15,
                            steps: 20,
                            cfg: 5,
                            image_required: true,
                            memory_mib: 18432,
                          },
                        }
                      : {}),
                    recommended_memory_profile: "bounded_11g",
                    memory_profiles: [
                      {
                        id: "bounded_11g",
                        available: true,
                        resolutions: portrait
                          ? [{ width: 704, height: 1280 }]
                          : [],
                      },
                    ],
                  }
                : {}),
            }
          : path.endsWith("/hardware")
            ? { gpus: [] }
            : path.includes("/artifacts/")
              ? {
                  id: "source",
                  type: "image",
                  mime_type: "image/png",
                  original_filename: "scene.png",
                }
              : path.includes("/media/jobs")
                ? {
                    task_id: "video-job",
                    revision: 1,
                    kind: "video",
                    mode: "continuous",
                    status: "queued",
                    active_run_ids: [],
                    duration_seconds: 10,
                    completed_segments: 0,
                    total_segments: 3,
                    final_artifact_id: null,
                  }
                : path.includes("/runs")
                  ? {
                      id: "video-run",
                      status: "queued",
                      parameters: options?.body
                        ? JSON.parse(String(options.body))
                        : {},
                    }
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

it("sends an explicit video translation override with the original scene unchanged", async () => {
  const fetch = mount();
  fireEvent.change(screen.getByLabelText("Scene and motion"), {
    target: { value: "Czerwony rower nad jeziorem" },
  });
  fireEvent.change(screen.getByLabelText("Prompt language"), {
    target: { value: "on" },
  });
  const submit = screen.getByRole("button", { name: "Generate video" });
  await waitFor(() => expect(submit.hasAttribute("disabled")).toBe(false));
  fireEvent.click(submit);
  await waitFor(() =>
    expect(
      fetch.mock.calls.some(
        ([path, options]) =>
          path === "/api/video/runs" && options?.method === "POST",
      ),
    ).toBe(true),
  );
  const call = fetch.mock.calls.find(
    ([path, options]) =>
      path === "/api/video/runs" && options?.method === "POST",
  )!;
  const body = JSON.parse(String(call[1]!.body));
  expect(body.prompt).toBe("Czerwony rower nad jeziorem");
  expect(body.translation).toEqual({
    mode: "on",
    review: false,
    protected_terms: [],
  });
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

it.each([5, 10])(
  "restores exact %s second duration, scene and dimensions from a saved media job",
  async (seconds) => {
    const fetch = vi.fn(async (url: string, init?: RequestInit) => {
      expect(init?.method).not.toBe("POST");
      return {
        ok: true,
        json: async () =>
          url.includes("/media/jobs/")
            ? {
                task_id: "saved",
                revision: 1,
                kind: "video",
                mode: "continuous",
                status: "succeeded",
                duration_seconds: seconds,
                completed_segments: 2,
                total_segments: 2,
                active_run_ids: [],
                final_artifact_id: null,
                resume_allowed: false,
                error_message: "",
                request: {
                  prompt: "Saved forest scene",
                  negative_prompt: "No captions",
                  width: 512,
                  height: 512,
                  duration_seconds: seconds,
                  composition_mode: "continuous",
                  steps: 4,
                  seed: 43,
                  gpu: "auto",
                },
              }
            : url.endsWith("/hardware")
              ? { gpus: [] }
              : { available: true, modes: ["generate", "animate"] },
      };
    });
    vi.stubGlobal("fetch", fetch);
    render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <MemoryRouter initialEntries={["/video?job=saved"]}>
          <Video />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await screen.findByDisplayValue("Saved forest scene");
    expect(screen.getByDisplayValue(`${seconds} seconds`)).toBeTruthy();
    expect(
      screen.getAllByRole("option", {
        name: `${seconds} seconds`,
      }),
    ).toHaveLength(1);
    expect(screen.getByDisplayValue("512 × 512")).toBeTruthy();
  },
);

it("offers a new ten-second continuous film without requiring a restored job", async () => {
  const fetch = mount();
  fireEvent.change(screen.getByLabelText("Scene and motion"), {
    target: { value: "A quiet lake" },
  });
  fireEvent.change(screen.getByLabelText("Duration"), {
    target: { value: "10s" },
  });
  expect(
    (screen.getByLabelText("Composition") as HTMLSelectElement).value,
  ).toBe("continuous");
  expect(
    fetch.mock.calls.some(([, options]) => options?.method === "POST"),
  ).toBe(false);
  const submit = screen.getByRole("button", { name: "Generate video" });
  await waitFor(() => expect(submit.hasAttribute("disabled")).toBe(false));
  fireEvent.click(submit);
  await waitFor(() => {
    const call = fetch.mock.calls.find(
      ([path, options]) =>
        path === "/api/media/jobs/video" && options?.method === "POST",
    );
    expect(call).toBeTruthy();
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
      duration_seconds: 10,
      composition_mode: "continuous",
      prompt: "A quiet lake",
    });
  });
});

it("preselects an installed video model and freezes it in a longer film request", async () => {
  const id = "cf567bf6-cd46-4102-992a-e7913c404f06";
  const fetch = mount(`/video?model=${id}`, true, [
    { id, name: "New Wan checkpoint", available: true },
  ]);
  const select = await screen.findByLabelText("Video model");
  expect((select as HTMLSelectElement).value).toBe(id);
  fireEvent.change(screen.getByLabelText("Scene and motion"), {
    target: { value: "A river at sunset" },
  });
  fireEvent.change(screen.getByLabelText("Duration"), {
    target: { value: "10s" },
  });
  await waitFor(() =>
    expect(
      (
        screen.getByRole("button", {
          name: "Generate video",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false),
  );
  fireEvent.click(screen.getByRole("button", { name: "Generate video" }));
  await waitFor(() =>
    expect(
      fetch.mock.calls.some(([path]) => path === "/api/media/jobs/video"),
    ).toBe(true),
  );
  const call = fetch.mock.calls.find(
    ([path]) => path === "/api/media/jobs/video",
  )!;
  expect(JSON.parse(String(call[1]?.body))).toMatchObject({
    model_id: id,
    memory_profile: "bounded_11g",
    width: 1280,
    height: 704,
    duration_seconds: 10,
  });
});

it("keeps an installed model selected while generating native portrait footage", async () => {
  const id = "5fe6a7d4-78d4-4bcf-873a-123456789abc";
  const fetch = mount(
    `/video?model=${id}`,
    true,
    [{ id, name: "Installed Wan", available: true }],
    true,
  );
  await screen.findByLabelText("Video model");
  await waitFor(() =>
    expect(
      (screen.getByLabelText("Format") as HTMLSelectElement).disabled,
    ).toBe(false),
  );
  fireEvent.change(screen.getByLabelText("Format"), {
    target: { value: "704x1280" },
  });
  fireEvent.change(screen.getByLabelText("Scene and motion"), {
    target: { value: "A vertical cinematic lighthouse shot" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Generate video" }));
  await waitFor(() =>
    expect(fetch.mock.calls.some(([path]) => path === "/api/video/runs")).toBe(
      true,
    ),
  );
  const call = fetch.mock.calls.find(([path]) => path === "/api/video/runs")!;
  expect(JSON.parse(String(call[1]?.body))).toMatchObject({
    model_id: id,
    memory_profile: "bounded_11g",
    width: 704,
    height: 1280,
  });
});

it("queues a five-minute film with a duration instead of short-clip frames", async () => {
  const fetch = mount();
  fireEvent.change(await screen.findByLabelText("Scene and motion"), {
    target: { value: "A long coastal study" },
  });
  fireEvent.change(screen.getByLabelText("Duration"), {
    target: { value: "300s" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Generate video" }));
  await waitFor(() =>
    expect(
      fetch.mock.calls.some(([path]) => path === "/api/media/jobs/video"),
    ).toBe(true),
  );
  const call = fetch.mock.calls.find(
    ([path]) => path === "/api/media/jobs/video",
  )!;
  const body = JSON.parse(String(call[1]?.body));
  expect(body.duration_seconds).toBe(300);
  expect(body).not.toHaveProperty("frames");
});

it.each(["81", "10s"])(
  "uses the selected recurrent model's recipe for duration %s",
  async (duration) => {
    const id = "cf567bf6-cd46-4102-992a-e7913c404f06";
    const fetch = mount(
      `/video?model=${id}&input=source`,
      true,
      [{ id, name: "Continuous video", available: true }],
      false,
      true,
    );
    await screen.findByText("scene.png");
    await screen.findByText(/18 GiB system RAM without swap/);
    expect((screen.getByLabelText("Format") as HTMLSelectElement).value).toBe(
      "832x480",
    );
    expect(
      (screen.getByLabelText("Format") as HTMLSelectElement).disabled,
    ).toBe(true);
    expect(
      (screen.getByRole("radio", { name: "Text to video" }) as HTMLInputElement)
        .disabled,
    ).toBe(true);
    expect(screen.getByRole("option", { name: "5.4 seconds" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: "3.4 seconds" })).toBeNull();
    expect(screen.getByText(/Output is 15 fps/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Scene and motion"), {
      target: { value: "A paper boat floats across a pond" },
    });
    fireEvent.change(screen.getByLabelText("Duration"), {
      target: { value: duration },
    });
    const submit = screen.getByRole("button", { name: "Generate video" });
    await waitFor(() => expect(submit.hasAttribute("disabled")).toBe(false));
    fireEvent.click(submit);
    const route =
      duration === "81" ? "/api/video/runs" : "/api/media/jobs/video";
    await waitFor(() =>
      expect(fetch.mock.calls.some(([path]) => path === route)).toBe(true),
    );
    const call = fetch.mock.calls.find(([path]) => path === route)!;
    const body = JSON.parse(String(call[1]?.body));
    expect(body).toMatchObject({
      model_id: id,
      image_artifact_id: "source",
      width: 832,
      height: 480,
      steps: 20,
      cfg: 5,
    });
    expect(body).not.toHaveProperty("memory_profile");
    if (duration === "81") expect(body.frames).toBe(81);
    else {
      expect(body.duration_seconds).toBe(10);
      expect(body.composition_mode).toBe("continuous");
      expect(body).not.toHaveProperty("frames");
    }
  },
);

it("requires an original image for the recurrent model, including direct form submission", async () => {
  const id = "cf567bf6-cd46-4102-992a-e7913c404f06";
  const fetch = mount(
    `/video?model=${id}`,
    true,
    [{ id, name: "Continuous video", available: true }],
    false,
    true,
  );
  await screen.findByText(/18 GiB system RAM without swap/);
  fireEvent.change(screen.getByLabelText("Scene and motion"), {
    target: { value: "A paper boat floats across a pond" },
  });
  const submit = screen.getByRole("button", { name: "Generate video" });
  expect(submit.hasAttribute("disabled")).toBe(true);
  fireEvent.submit(submit.closest("form")!);
  expect(
    fetch.mock.calls.some(([, options]) => options?.method === "POST"),
  ).toBe(false);
});
