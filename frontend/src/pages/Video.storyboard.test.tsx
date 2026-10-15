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
  sessionStorage.clear();
});
const scenes = [
  { prompt: "Opening forest", duration_seconds: 2 },
  { prompt: "Closing ocean", duration_seconds: 4 },
];
function mount(saved = false, busy = false) {
  const writes: { path: string; body: Record<string, unknown> }[] = [];
  const job = {
    task_id: "job",
    kind: "video",
    mode: "shots",
    status: busy ? "generating" : "canceled",
    revision: 1,
    duration_seconds: 6,
    completed_segments: 0,
    total_segments: 3,
    active_run_ids: busy ? ["run"] : [],
    final_artifact_id: null,
    resume_allowed: !busy,
    error_message: "",
    request: {
      prompt: "Warm light",
      duration_seconds: 6,
      composition_mode: "shots",
      scenes,
    },
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "POST")
        writes.push({ path, body: JSON.parse(String(init.body)) });
      return {
        ok: true,
        json: async () =>
          path.endsWith("/capabilities")
            ? { available: true }
            : path.endsWith("/hardware")
              ? { gpus: [] }
              : path.includes("/media/jobs")
                ? job
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
      <MemoryRouter initialEntries={[saved ? "/video?job=job" : "/video"]}>
        <Video />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return writes;
}
async function plan() {
  fireEvent.change(screen.getByLabelText("Scene and motion"), {
    target: { value: "Warm light" },
  });
  fireEvent.change(screen.getByLabelText("Duration"), {
    target: { value: "15s" },
  });
  fireEvent.change(screen.getByLabelText("Composition"), {
    target: { value: "shots" },
  });
  fireEvent.click(screen.getByLabelText("Plan individual scenes"));
  await screen.findByRole("region", { name: "Scene plan" });
}
it("edits, reorders and removes scenes, then sends only the ordered plan and calculated duration", async () => {
  const writes = mount();
  await plan();
  fireEvent.change(screen.getByLabelText("Scene 1 prompt"), {
    target: { value: "Opening forest" },
  });
  fireEvent.change(screen.getByLabelText("Scene 1 duration"), {
    target: { value: "2" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Add scene" }));
  await waitFor(() =>
    expect(document.activeElement).toBe(
      screen.getByLabelText("Scene 2 prompt"),
    ),
  );
  fireEvent.change(screen.getByLabelText("Scene 2 prompt"), {
    target: { value: "Closing ocean" },
  });
  fireEvent.change(screen.getByLabelText("Scene 2 duration"), {
    target: { value: "4" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Move scene 2 earlier" }));
  await waitFor(() =>
    expect(document.activeElement).toBe(
      screen.getByLabelText("Scene 1 prompt"),
    ),
  );
  expect(
    (screen.getByLabelText("Scene 1 prompt") as HTMLTextAreaElement).value,
  ).toBe("Closing ocean");
  expect(screen.getByLabelText("Planned duration").textContent).toContain(
    "6 seconds",
  );
  fireEvent.click(screen.getByRole("button", { name: "Remove scene 2" }));
  await waitFor(() =>
    expect(document.activeElement).toBe(
      screen.getByLabelText("Scene 1 prompt"),
    ),
  );
  expect(
    (screen.getByLabelText("Scene 1 duration") as HTMLInputElement).value,
  ).toBe("4");
  fireEvent.click(screen.getByRole("button", { name: "Add scene" }));
  expect(
    screen
      .getByRole("button", { name: "Generate video" })
      .hasAttribute("disabled"),
  ).toBe(true);
  fireEvent.change(screen.getByLabelText("Scene 2 prompt"), {
    target: { value: "A distant mountain" },
  });
  await waitFor(() =>
    expect(
      screen
        .getByRole("button", { name: "Generate video" })
        .hasAttribute("disabled"),
    ).toBe(false),
  );
  fireEvent.click(screen.getByRole("button", { name: "Generate video" }));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0].path).toBe("/api/media/jobs/video");
  expect(writes[0].body).toMatchObject({
    duration_seconds: 9,
    composition_mode: "shots",
    scenes: [
      { prompt: "Closing ocean", duration_seconds: 4 },
      { prompt: "A distant mountain", duration_seconds: 5 },
    ],
  });
  expect(JSON.stringify(writes[0].body.scenes)).not.toContain('"key"');
});
it("restores saved scenes without writes and keeps continuous requests free of scene fields", async () => {
  const writes = mount(true);
  const first = await screen.findByLabelText("Scene 1 prompt");
  expect((first as HTMLTextAreaElement).value).toBe("Opening forest");
  expect(screen.getByLabelText("Planned duration").textContent).toContain(
    "6 seconds",
  );
  expect(writes).toHaveLength(0);
  fireEvent.change(screen.getByLabelText("Composition"), {
    target: { value: "continuous" },
  });
  expect(screen.queryByRole("region", { name: "Scene plan" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Generate video" }));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0].body.composition_mode).toBe("continuous");
  expect(writes[0].body).not.toHaveProperty("scenes");
});
it("rejects excessive total and combined prompts in place before a request", async () => {
  const writes = mount();
  await plan();
  fireEvent.change(screen.getByLabelText("Scene 1 prompt"), {
    target: { value: "A forest" },
  });
  fireEvent.change(screen.getByLabelText("Scene 1 duration"), {
    target: { value: "60" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Add scene" }));
  fireEvent.change(screen.getByLabelText("Scene 2 prompt"), {
    target: { value: "An ocean" },
  });
  expect(
    screen.getByText("The complete film can be up to 60 seconds."),
  ).toBeTruthy();
  expect(
    screen
      .getByRole("button", { name: "Generate video" })
      .hasAttribute("disabled"),
  ).toBe(true);
  fireEvent.change(screen.getByLabelText("Scene 1 duration"), {
    target: { value: "2" },
  });
  fireEvent.change(screen.getByLabelText("Shared style and setting"), {
    target: { value: "x".repeat(1999) },
  });
  expect(
    screen.getByText(
      "Shared instructions and each scene must fit 2000 characters together.",
    ),
  ).toBeTruthy();
  expect(writes).toHaveLength(0);
});
it("disables all restored scene controls while the saved job is active", async () => {
  const writes = mount(true, true);
  const field = await screen.findByLabelText("Scene 1 prompt");
  expect(field.matches(":disabled")).toBe(true);
  expect(
    screen.getByRole("button", { name: "Add scene" }).matches(":disabled"),
  ).toBe(true);
  expect(writes).toHaveLength(0);
});
