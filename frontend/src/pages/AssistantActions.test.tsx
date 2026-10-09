import { emptyOptions } from "./assistant-options";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { useState } from "react";
import AssistantActions, { AssistantResults } from "./AssistantActions";

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

it("shows a failed child even when planning succeeded", () => {
  render(
    <MemoryRouter>
      <AssistantResults
        result={{
          task_status: "failed",
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
          ],
          artifacts: [],
        }}
      />
    </MemoryRouter>,
  );
  expect(screen.getByText("GPU unavailable")).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "image.recompose" }).getAttribute("href"),
  ).toBe("/runs/image");
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

it("stages inline results as next-message inputs and prevents duplicate reuse", () => {
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
  const { rerender } = render(
    <MemoryRouter>
      <AssistantResults result={result} inputs={emptyOptions} onUse={use} />
    </MemoryRouter>,
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Use as image reference" }),
  );
  expect(use).toHaveBeenCalledWith(artifact);
  rerender(
    <MemoryRouter>
      <AssistantResults
        result={result}
        inputs={{ ...emptyOptions, image_artifact_ids: ["result"] }}
        onUse={use}
      />
    </MemoryRouter>,
  );
  expect(
    screen
      .getByRole("button", { name: "Added to next message" })
      .hasAttribute("disabled"),
  ).toBe(true);
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
  fireEvent.change(screen.getByLabelText("Action"), {
    target: { value: "coding.local" },
  });
  await screen.findByRole("option", { name: "AI Station" });
  fireEvent.change(screen.getByLabelText("Project"), {
    target: { value: "project-1" },
  });
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
  const repairList = screen.getByLabelText("Repair 0").closest(
    ".repair-choice-list",
  ) as HTMLElement;
  fireEvent.keyDown(repairList, { key: "End" });
  fireEvent.keyDown(repairList, { key: "Enter" });
  expect(
    JSON.parse(screen.getByTestId("scope").textContent!).max_repair_attempts,
  ).toBe(2);
  fireEvent.change(screen.getByLabelText("Action"), {
    target: { value: "coding.cursor" },
  });
  expect(screen.getByTestId("scope").textContent).toBe("null");
  fireEvent.click(screen.getByRole("checkbox", { name: /Allow sending/ }));
  expect(JSON.parse(screen.getByTestId("scope").textContent!).external_ai).toBe(
    true,
  );
  expect(
    JSON.parse(screen.getByTestId("scope").textContent!).max_repair_attempts,
  ).toBeUndefined();
  fireEvent.change(screen.getByLabelText("Action"), {
    target: { value: "coding.codex" },
  });
  expect(screen.getByTestId("scope").textContent).toBe("null");
  fireEvent.click(screen.getByRole("checkbox", { name: /Allow sending/ }));
  expect(JSON.parse(screen.getByTestId("scope").textContent!).executor).toBe(
    "codex",
  );
  fireEvent.change(screen.getByLabelText("Action"), {
    target: { value: "coding.local" },
  });
  expect(JSON.parse(screen.getByTestId("scope").textContent!).external_ai).toBe(
    false,
  );
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
  fireEvent.change(screen.getByLabelText("Action"), {
    target: { value: "coding.commit" },
  });
  expect(screen.getByTestId("commit").textContent).toBe("null");
  fireEvent.change(screen.getByLabelText("Commit proposal"), {
    target: { value: "proposal" },
  });
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
  fireEvent.change(screen.getByLabelText("Action"), {
    target: { value: "runtime.load" },
  });
  expect(screen.getByTestId("load").textContent).toBe("null");
  await screen.findByRole("option", { name: /assistant.gguf/ });
  fireEvent.change(screen.getByLabelText("GGUF model"), {
    target: { value: "gguf-1" },
  });
  expect(JSON.parse(screen.getByTestId("load").textContent!)).toMatchObject({
    model_file_id: "gguf-1",
    context_size: 4096,
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
