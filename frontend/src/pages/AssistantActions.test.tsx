import { emptyOptions } from "./assistant-options";
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
import { useState } from "react";
import AssistantActions, { AssistantResults } from "./AssistantActions";

function chooseAction(key: string) {
  fireEvent.click(
    screen
      .getByLabelText(`Action ${key}`)
      .querySelector("input") as HTMLElement,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("keeps ordered image uploads and removes one reference", async () => {
  let next = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({ id: `image-${++next}` }),
    })),
  );
  function Composer() {
    const [value, setValue] = useState(emptyOptions);
    const [busy, setBusy] = useState(false);
    return (
      <AssistantActions
        value={value}
        onChange={setValue}
        busy={busy}
        onUploading={setBusy}
      />
    );
  }
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Composer />
    </QueryClientProvider>,
  );
  fireEvent.change(screen.getByLabelText("Image references"), {
    target: {
      files: [new File(["a"], "person.png"), new File(["b"], "clothing.png")],
    },
  });
  const second = await screen.findByAltText("Reference 2");
  expect(second.getAttribute("src")).toBe("/api/artifacts/image-2/file");
  fireEvent.click(
    screen.getByRole("button", { name: "Remove reference 1 image-1" }),
  );
  expect(screen.getByAltText("Reference 1").getAttribute("src")).toBe(
    "/api/artifacts/image-2/file",
  );
  expect(screen.queryByAltText("Reference 2")).toBeNull();
});

function failedImageResult(
  extra: NonNullable<
    Parameters<typeof AssistantResults>[0]["result"]["steps"]
  > = [],
) {
  return {
    task_status: "failed" as const,
    steps: [
      {
        id: "plan",
        capability: "assistant.orchestrate",
        status: "succeeded",
        summary: "",
        error_message: "",
        location: "local",
      },
      {
        id: "image",
        capability: "image.recompose",
        status: "failed",
        summary: "",
        error_message: "GPU unavailable",
        location: "local",
      },
      ...extra,
    ],
    artifacts: [] as [],
  };
}

function mountResults(
  result: Parameters<typeof AssistantResults>[0]["result"],
  onQueued?: Parameters<typeof AssistantResults>[0]["onQueued"],
) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <AssistantResults result={result} onQueued={onQueued} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("shows a failed child even when planning succeeded", () => {
  mountResults(failedImageResult());
  expect(screen.getByText("GPU unavailable")).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "image.recompose" }).getAttribute("href"),
  ).toBe("/runs/image");
});

it("retries a failed image step in the conversation without opening the inspector", async () => {
  const queued = vi.fn();
  const fetch = vi.fn(async (path: string, options?: RequestInit) => ({
    ok: true,
    json: async () =>
      options?.method === "POST" && String(path).endsWith("/retry")
        ? { id: "retry-id", status: "queued" }
        : { id: "image", sources: [], derived: [] },
  }));
  vi.stubGlobal("fetch", fetch);
  mountResults(failedImageResult(), queued);
  fireEvent.click(
    screen.getByRole("button", { name: "Retry as a new run image" }),
  );
  await waitFor(() =>
    expect(queued).toHaveBeenCalledWith({
      id: "retry-id",
      status: "queued",
    }),
  );
  expect(fetch).toHaveBeenCalledWith(
    "/api/images/runs/image/retry",
    expect.objectContaining({ method: "POST" }),
  );
  expect(screen.queryByRole("heading", { name: "Run inspector" })).toBeNull();
  expect(screen.queryByRole("link", { name: /Images/ })).toBeNull();
});

it("does not retry audio, avatars, or an image step that already has a later image run", () => {
  mountResults({
    task_status: "failed",
    steps: [
      {
        id: "speech",
        capability: "audio.speech",
        status: "failed",
        summary: "",
        error_message: "Chatterbox missing",
        location: "local",
      },
      {
        id: "avatar",
        capability: "avatar.animate",
        status: "canceled",
        summary: "",
        error_message: "",
        location: "local",
      },
      {
        id: "image",
        capability: "image.generate",
        status: "failed",
        summary: "",
        error_message: "GPU lost",
        location: "local",
      },
      {
        id: "retry-id",
        capability: "image.generate",
        status: "queued",
        summary: "",
        error_message: "",
        location: "local",
      },
    ],
    artifacts: [],
  });
  expect(
    screen.queryByRole("button", { name: /Retry as a new run/ }),
  ).toBeNull();
});

it("reuses Library images in selection order, reorders them, and attaches a voice without uploads", async () => {
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () =>
      path.includes("kind=audio")
        ? [
            {
              id: "voice",
              type: "audio",
              mime_type: "audio/wav",
              original_filename: "Voice.wav",
              metadata: {},
            },
          ]
        : [
            {
              id: "person",
              type: "image",
              mime_type: "image/png",
              original_filename: "Person.png",
              metadata: { width: 512, height: 512 },
            },
            {
              id: "outfit",
              type: "image",
              mime_type: "image/jpeg",
              original_filename: "Outfit.jpg",
              metadata: { width: 512, height: 512 },
            },
          ],
  }));
  vi.stubGlobal("fetch", fetch);
  function Composer() {
    const [value, setValue] = useState(emptyOptions);
    return (
      <AssistantActions
        value={value}
        onChange={setValue}
        busy={false}
        onUploading={() => {}}
      />
    );
  }
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Composer />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Images from Library" }));
  fireEvent.click(await screen.findByRole("button", { name: /Outfit\.jpg/ }));
  fireEvent.click(screen.getByRole("button", { name: /Person\.png/ }));
  fireEvent.click(screen.getByRole("button", { name: "Attach 2 files" }));
  expect(screen.getByAltText("Reference 1").getAttribute("src")).toBe(
    "/api/artifacts/outfit/file",
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Move reference 2 person earlier" }),
  );
  expect(screen.getByAltText("Reference 1").getAttribute("src")).toBe(
    "/api/artifacts/person/file",
  );
  fireEvent.click(screen.getByRole("button", { name: "Voice from Library" }));
  fireEvent.click(await screen.findByRole("button", { name: /Voice\.wav/ }));
  fireEvent.click(screen.getByRole("button", { name: "Attach file" }));
  expect(
    screen.getByLabelText("Voice reference preview").getAttribute("src"),
  ).toBe("/api/artifacts/voice/file");
  expect(
    fetch.mock.calls.every(([path]) => path.startsWith("/api/artifacts?")),
  ).toBe(true);
  fireEvent.click(
    screen.getByRole("button", { name: "Remove voice reference" }),
  );
  expect(screen.queryByLabelText("Voice reference preview")).toBeNull();
});

it("stages inline results as next-message inputs and prevents duplicate reuse", async () => {
  const use = vi.fn();
  const artifact = {
    id: "result",
    type: "image",
    mime_type: "image/png",
    original_filename: "result.png",
    metadata: {},
    parent_artifact_ids: [],
    size_bytes: 20,
    created_at: "2026-09-29T00:00:00Z",
    run_id: null,
  };
  const result = { steps: [], artifacts: [artifact] };
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({ id: artifact.id, sources: [], derived: [] }),
    })),
  );
  const tree = (inputs = emptyOptions) => (
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <AssistantResults result={result} inputs={inputs} onUse={use} />
      </MemoryRouter>
    </QueryClientProvider>
  );
  const { rerender } = render(tree());
  await screen.findByRole("button", { name: "Use as image reference" });
  fireEvent.click(
    screen.getByRole("button", { name: "Use as image reference" }),
  );
  expect(use).toHaveBeenCalledWith(artifact);
  rerender(tree({ ...emptyOptions, image_artifact_ids: ["result"] }));
  expect(
    screen
      .getByRole("button", { name: "Added to next message" })
      .hasAttribute("disabled"),
  ).toBe(true);
  expect(
    screen.getByRole("link", { name: "Edit result" }).getAttribute("href"),
  ).toBe("/images?mode=img2img&input=result");
  expect(
    screen.getByRole("link", { name: "Recompose result" }).getAttribute("href"),
  ).toBe("/images?mode=recompose&input=result");
  expect(
    screen.getByRole("link", { name: "Upscale result" }).getAttribute("href"),
  ).toBe("/images?mode=upscale&input=result");
  expect(
    screen
      .getByRole("link", { name: "Use as portrait result" })
      .getAttribute("href"),
  ).toBe("/avatars?image=result");
});

it("edits Library details on an inline result without queueing a Run", async () => {
  const artifact = {
    id: "result",
    type: "image",
    mime_type: "image/png",
    original_filename: "result.png",
    title: "Result",
    notes: "",
    library_updated_at: "2026-10-11T10:00:00Z",
    metadata: {},
    parent_artifact_ids: [],
    size_bytes: 20,
    created_at: "2026-09-29T00:00:00Z",
    run_id: null,
  };
  const fetch = vi.fn(async (path: string, init?: RequestInit) => {
    if (init?.method === "PATCH") {
      return {
        ok: true,
        json: async () => ({ ...artifact, title: "Named still" }),
      };
    }
    return {
      ok: true,
      json: async () =>
        String(path).endsWith("/lineage")
          ? { id: artifact.id, sources: [], derived: [] }
          : artifact,
    };
  });
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <AssistantResults result={{ steps: [], artifacts: [artifact] }} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Edit details result" }),
  );
  fireEvent.change(screen.getByLabelText("Display name"), {
    target: { value: "Named still" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save details" }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/artifacts/result",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({
          expected_updated_at: "2026-10-11T10:00:00Z",
          title: "Named still",
          notes: "",
        }),
      }),
    ),
  );
  expect(
    fetch.mock.calls.every((call) => (call[1]?.method ?? "GET") !== "POST"),
  ).toBe(true);
});

it("stages inline speech into Audio and Avatars without inventing a Run", async () => {
  const spoken = {
    id: "spoken01",
    type: "audio",
    mime_type: "audio/wav",
    original_filename: "line.wav",
    title: "Spoken line",
    metadata: {},
    parent_artifact_ids: [],
    size_bytes: 20,
    created_at: "2026-09-29T00:00:00Z",
    run_id: "speech",
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({ id: spoken.id, sources: [], derived: [] }),
    })),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <AssistantResults
          result={{ steps: [], artifacts: [spoken] }}
          inputs={emptyOptions}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(
    (
      await screen.findByRole("link", { name: "Use in Audio spoken01" })
    ).getAttribute("href"),
  ).toBe("/audio?input=spoken01&run=speech");
  expect(
    screen
      .getByRole("link", { name: "Use as speech spoken01" })
      .getAttribute("href"),
  ).toBe("/avatars?audio=spoken01");
});

it("shows shared lineage on inline media results without inventing a Run", async () => {
  const portrait = {
    id: "portrait1",
    type: "image",
    mime_type: "image/png",
    original_filename: "portrait.png",
    title: "Portrait",
    metadata: {},
    parent_artifact_ids: [],
    size_bytes: 20,
    created_at: "2026-09-29T00:00:00Z",
    run_id: null,
  };
  const video = {
    ...portrait,
    id: "avatar01",
    type: "video",
    mime_type: "video/mp4",
    original_filename: "avatar.mp4",
    title: "Avatar take",
    parent_artifact_ids: ["portrait1"],
    metadata: { capability: "avatar.animate" },
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      expect(init?.method ?? "GET").toBe("GET");
      return {
        ok: true,
        json: async () =>
          String(path).endsWith("/lineage")
            ? { id: video.id, sources: [portrait], derived: [] }
            : video,
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
        <AssistantResults result={{ steps: [], artifacts: [video] }} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const source = await screen.findByRole("link", {
    name: "Inspect source Portrait portrait",
  });
  expect(source.getAttribute("href")).toBe("/library/portrait1");
  expect(screen.getByText(/There is no inspectable lineage Run/)).toBeTruthy();
});

it("stages local coding scope without granting Cursor consent", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => [
        {
          id: "project-1",
          name: "AI Station",
          updated_at: "2026-09-29T00:00:00Z",
        },
      ],
    })),
  );
  function Composer() {
    const [value, setValue] = useState(emptyOptions);
    return (
      <>
        <AssistantActions
          value={value}
          onChange={setValue}
          busy={false}
          onUploading={() => {}}
        />
        <output data-testid="scope">{JSON.stringify(value.coding)}</output>
      </>
    );
  }
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Composer />
    </QueryClientProvider>,
  );
  chooseAction("coding.local");
  const projectList = (
    await screen.findByLabelText("Project project-1")
  ).closest(".project-choice-list") as HTMLElement;
  fireEvent.keyDown(projectList, { key: "Enter" });
  expect(
    screen.getByText(/There is no inspectable project-selection Run/),
  ).toBeTruthy();
  expect(JSON.parse(screen.getByTestId("scope").textContent!)).toMatchObject({
    files: [],
    explore: true,
    external_ai: false,
  });
  expect(
    screen.getByText(/Public URLs in the task are fetched automatically/),
  ).toBeTruthy();
  fireEvent.click(
    screen.getByRole("checkbox", {
      name: "Let Local AI find the relevant files",
    }),
  );
  fireEvent.change(screen.getByLabelText("Selected files"), {
    target: { value: "README.md\nsrc/app.py" },
  });
  expect(JSON.parse(screen.getByTestId("scope").textContent!)).toEqual({
    project_id: "project-1",
    expected_updated_at: "2026-09-29T00:00:00Z",
    files: ["README.md", "src/app.py"],
    external_ai: false,
  });
  expect(
    (
      screen.getByRole("checkbox", {
        name: "Let Local AI find the relevant files",
      }) as HTMLInputElement
    ).checked,
  ).toBe(false);
  expect(
    (
      screen.getByRole("radio", {
        name: /Off — ask me first/,
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
  const repairList = screen
    .getByLabelText("Repair 0")
    .closest(".repair-choice-list") as HTMLElement;
  fireEvent.keyDown(repairList, { key: "End" });
  fireEvent.keyDown(repairList, { key: "Enter" });
  expect(
    JSON.parse(screen.getByTestId("scope").textContent!).max_repair_attempts,
  ).toBe(2);
  chooseAction("coding.cursor");
  expect(screen.getByTestId("scope").textContent).toBe("null");
  fireEvent.click(screen.getByRole("checkbox", { name: /Allow sending/ }));
  expect(JSON.parse(screen.getByTestId("scope").textContent!).external_ai).toBe(
    true,
  );
  expect(
    JSON.parse(screen.getByTestId("scope").textContent!).max_repair_attempts,
  ).toBeUndefined();
  chooseAction("coding.codex");
  expect(screen.getByTestId("scope").textContent).toBe("null");
  fireEvent.click(screen.getByRole("checkbox", { name: /Allow sending/ }));
  expect(JSON.parse(screen.getByTestId("scope").textContent!).executor).toBe(
    "codex",
  );
  chooseAction("coding.local");
  expect(JSON.parse(screen.getByTestId("scope").textContent!).external_ai).toBe(
    false,
  );
});

it("selects a native Cursor model without sending", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => ({
      ok: true,
      json: async () =>
        String(path).includes("/coding/models/")
          ? {
              models: [{ id: "available-model", name: "Available model" }],
              notice: "",
            }
          : [
              {
                id: "project-1",
                name: "AI Station",
                updated_at: "2026-09-29T00:00:00Z",
              },
            ],
    })),
  );
  function Composer() {
    const [value, setValue] = useState(emptyOptions);
    return (
      <form
        onSubmit={(event) => {
          event.preventDefault();
          throw new Error("form submitted");
        }}
      >
        <AssistantActions
          value={value}
          onChange={setValue}
          busy={false}
          onUploading={() => {}}
        />
        <output data-testid="scope">{JSON.stringify(value.coding)}</output>
        <button type="submit">Send</button>
      </form>
    );
  }
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Composer />
    </QueryClientProvider>,
  );
  chooseAction("coding.cursor");
  fireEvent.keyDown(
    (await screen.findByLabelText("Project project-1")).closest(
      ".project-choice-list",
    ) as HTMLElement,
    { key: "Enter" },
  );
  await screen.findByLabelText("Model available-model");
  expect(
    (
      screen
        .getByLabelText("Model auto")
        .querySelector("input") as HTMLInputElement
    ).checked,
  ).toBe(true);
  fireEvent.click(
    screen
      .getByLabelText("Model available-model")
      .querySelector("input") as HTMLElement,
  );
  fireEvent.click(screen.getByRole("checkbox", { name: /Allow sending/ }));
  expect(JSON.parse(screen.getByTestId("scope").textContent!)).toMatchObject({
    model: "available-model",
    explore: true,
    files: [],
  });
  const list = screen
    .getByLabelText("Model auto")
    .closest(".coding-model-choice-list") as HTMLElement;
  fireEvent.keyDown(list, { key: "Home" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(
    JSON.parse(screen.getByTestId("scope").textContent!).model,
  ).toBeUndefined();
  expect(
    screen.getByText(/There is no inspectable model-selection Run/),
  ).toBeTruthy();
});

it("enables Cursor automatic file discovery without sending", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => [
        {
          id: "project-1",
          name: "AI Station",
          updated_at: "2026-09-29T00:00:00Z",
        },
      ],
    })),
  );
  function Composer() {
    const [value, setValue] = useState(emptyOptions);
    return (
      <>
        <AssistantActions
          value={value}
          onChange={setValue}
          busy={false}
          onUploading={() => {}}
        />
        <output data-testid="scope">{JSON.stringify(value.coding)}</output>
      </>
    );
  }
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Composer />
    </QueryClientProvider>,
  );
  chooseAction("coding.cursor");
  fireEvent.keyDown(
    (await screen.findByLabelText("Project project-1")).closest(
      ".project-choice-list",
    ) as HTMLElement,
    { key: "Enter" },
  );
  expect(
    screen.getByRole("checkbox", {
      name: "Let the agent find the relevant files",
    }),
  ).toBeTruthy();
  expect(screen.queryByLabelText("Selected files")).toBeNull();
  fireEvent.click(screen.getByRole("checkbox", { name: /Allow sending/ }));
  expect(JSON.parse(screen.getByTestId("scope").textContent!)).toMatchObject({
    files: [],
    explore: true,
    external_ai: true,
  });
  fireEvent.click(
    screen.getByRole("checkbox", {
      name: "Let the agent find the relevant files",
    }),
  );
  expect(screen.getByTestId("scope").textContent).toBe("null");
  expect(screen.getByLabelText("Selected files")).toBeTruthy();
});

it("requires an in-conversation proposal and review before commit action is ready", async () => {
  function Composer() {
    const [value, setValue] = useState(emptyOptions);
    return (
      <>
        <AssistantActions
          value={value}
          onChange={setValue}
          busy={false}
          onUploading={() => {}}
          sources={[
            {
              id: "proposal",
              executor_type: "local_proposal",
              status: "succeeded",
              summary: "Update app.py",
              capability: "coding.local",
              metadata: {
                coding_review: {
                  files: [{ path: "app.py", diff: "+x", insertions: 1 }],
                },
              },
            } as never,
          ]}
        />
        <output data-testid="commit">{JSON.stringify(value.commit)}</output>
      </>
    );
  }
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Composer />
    </QueryClientProvider>,
  );
  chooseAction("coding.commit");
  expect(screen.getByTestId("commit").textContent).toBe("null");
  const proposalList = screen
    .getByLabelText("Proposal proposal")
    .closest(".proposal-choice-list") as HTMLElement;
  fireEvent.keyDown(proposalList, { key: "Enter" });
  expect(
    screen.getByText(/There is no inspectable proposal-selection Run/),
  ).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Commit message"), {
    target: { value: "Accept reviewed edits" },
  });
  expect(screen.getByTestId("commit").textContent).toBe("null");
  fireEvent.click(
    screen.getByRole("checkbox", {
      name: "I reviewed the diff and validation results.",
    }),
  );
  expect(JSON.parse(screen.getByTestId("commit").textContent!)).toEqual({
    source_run_id: "proposal",
    message: "Accept reviewed edits",
    reviewed: true,
  });
});

it("renders review and commit controls from conversation coding runs", () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <AssistantResults
          result={{
            task_status: "succeeded",
            steps: [
              {
                id: "proposal",
                capability: "coding.local",
                status: "succeeded",
                summary: "Update app.py",
                error_message: "",
                location: "local",
              },
            ],
            artifacts: [],
            coding_runs: [
              {
                id: "proposal",
                status: "succeeded",
                summary: "Update app.py",
                executor_type: "local_proposal",
                project_id: "project-1",
                metadata: {
                  coding_review: {
                    branch: "ai/task",
                    files: [
                      {
                        path: "app.py",
                        diff: "+print(1)",
                        insertions: 1,
                        deletions: 0,
                      },
                    ],
                  },
                },
              } as never,
            ],
          }}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(screen.getByText("Changes awaiting review")).toBeTruthy();
  expect(
    screen.getByRole("button", { name: "Commit reviewed changes" }),
  ).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "Inspect project project-1" }).getAttribute(
      "href",
    ),
  ).toBe("/projects/project-1");
  expect(
    screen
      .getByRole("link", { name: "View tagged Runs project-1" })
      .getAttribute("href"),
  ).toBe("/runs?project_id=project-1");
});

it("opens tagged Runs from conversation coding results without starting a Run", () => {
  const fetch = vi.fn(async (path: string) => ({
    ok: true,
    json: async () => (path.includes("/api/") ? [] : []),
  }));
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <AssistantResults
          result={{
            task_status: "succeeded",
            steps: [
              {
                id: "proposal",
                capability: "coding.local",
                status: "succeeded",
                summary: "Update app.py",
                error_message: "",
                location: "local",
              },
            ],
            artifacts: [],
            coding_runs: [
              {
                id: "proposal",
                status: "succeeded",
                summary: "Update app.py",
                executor_type: "local_proposal",
                project_id: "project-1",
                metadata: {
                  coding_review: {
                    branch: "ai/task",
                    files: [{ path: "app.py", diff: "+x", insertions: 1 }],
                  },
                },
              } as never,
            ],
          }}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(
    screen.getByRole("link", { name: "Inspect project project-1" }).getAttribute(
      "href",
    ),
  ).toBe("/projects/project-1");
  expect(
    screen
      .getByRole("link", { name: "View tagged Runs project-1" })
      .getAttribute("href"),
  ).toBe("/runs?project_id=project-1");
  expect(screen.queryByRole("button", { name: /Enable/i })).toBeNull();
  expect(screen.queryByRole("button", { name: /Run now/i })).toBeNull();
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).includes("/coding/cursor")),
  ).toBe(true);
  expect(
    fetch.mock.calls.every((call) => !String(call[0]).includes("/messages")),
  ).toBe(true);
});

it("requires an explicit GGUF before a load action is ready", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => ({
      ok: true,
      json: async () =>
        String(path).includes("/llama")
          ? {
              models: [{ id: "gguf-1", name: "models · assistant.gguf" }],
              instances: [],
            }
          : { gpus: [{ index: 0, name: "GPU 0" }] },
    })),
  );
  function Composer() {
    const [value, setValue] = useState(emptyOptions);
    return (
      <>
        <AssistantActions
          value={value}
          onChange={setValue}
          busy={false}
          onUploading={() => {}}
        />
        <output data-testid="load">{JSON.stringify(value.load)}</output>
      </>
    );
  }
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Composer />
    </QueryClientProvider>,
  );
  chooseAction("runtime.load");
  expect(screen.getByTestId("load").textContent).toBe("null");
  const ggufList = (await screen.findByLabelText("GGUF gguf-1")).closest(
    ".gguf-choice-list",
  ) as HTMLElement;
  fireEvent.keyDown(ggufList, { key: "Enter" });
  expect(
    screen.getByText(/There is no inspectable GGUF-selection Run/),
  ).toBeTruthy();
  expect(JSON.parse(screen.getByTestId("load").textContent!)).toMatchObject({
    model_file_id: "gguf-1",
    context_size: 4096,
  });
});

it("selects an owned runtime without listing external servers", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({
        models: [],
        instances: [
          {
            id: "owned",
            name: "27B",
            status: "ready",
            ownership: "managed",
          },
          {
            id: "ext",
            name: "Ollama",
            status: "ready",
            ownership: "external",
          },
          {
            id: "dead",
            name: "Stopped",
            status: "stopped",
            ownership: "managed",
          },
        ],
      }),
    })),
  );
  function Composer() {
    const [value, setValue] = useState(emptyOptions);
    return (
      <>
        <AssistantActions
          value={value}
          onChange={setValue}
          busy={false}
          onUploading={() => {}}
        />
        <output data-testid="stop">{JSON.stringify(value.stop)}</output>
      </>
    );
  }
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Composer />
    </QueryClientProvider>,
  );
  chooseAction("runtime.stop");
  const runtimeList = (await screen.findByLabelText("Runtime owned")).closest(
    ".runtime-choice-list",
  ) as HTMLElement;
  expect(screen.queryByLabelText("Runtime ext")).toBeNull();
  expect(screen.queryByLabelText("Runtime dead")).toBeNull();
  fireEvent.keyDown(runtimeList, { key: "Enter" });
  expect(
    screen.getByText(/There is no inspectable runtime-selection Run/),
  ).toBeTruthy();
  expect(JSON.parse(screen.getByTestId("stop").textContent!)).toEqual({
    instance_id: "owned",
  });
});

it("moves through image references with arrow keys without inventing a Run", async () => {
  let uploaded = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({ id: `image-${++uploaded}` }),
    })),
  );
  function Composer() {
    const [value, setValue] = useState(emptyOptions);
    return (
      <AssistantActions
        value={value}
        onChange={setValue}
        busy={false}
        onUploading={() => {}}
      />
    );
  }
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Composer />
    </QueryClientProvider>,
  );
  fireEvent.change(screen.getByLabelText("Image references"), {
    target: {
      files: [new File(["a"], "person.png"), new File(["b"], "clothing.png")],
    },
  });
  const first = await screen.findByLabelText("Image reference 1 image-1");
  const second = screen.getByLabelText("Image reference 2 image-2");
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  expect(
    screen.getByText(/There is no inspectable reference Run/),
  ).toBeTruthy();
  fireEvent.keyDown(
    first.closest(".assistant-reference-strip") as HTMLElement,
    { key: "ArrowRight" },
  );
  expect(second.tabIndex).toBe(0);
  expect(document.activeElement).toBe(second);
  expect(
    screen.getByRole("button", { name: "Remove reference 2 image-2" }).tabIndex,
  ).toBe(0);
  fireEvent.keyDown(
    second.closest(".assistant-reference-strip") as HTMLElement,
    { key: "Enter" },
  );
  expect(screen.getByLabelText("Image reference 2 image-2")).toBeTruthy();
  fireEvent.keyDown(
    second.closest(".assistant-reference-strip") as HTMLElement,
    { key: "Home" },
  );
  expect(first.tabIndex).toBe(0);
});
