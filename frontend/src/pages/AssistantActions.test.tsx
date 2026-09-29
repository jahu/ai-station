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
  fireEvent.click(screen.getByRole("button", { name: "Remove reference 1" }));
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
  fireEvent.click(await screen.findByRole("button", { name: "Outfit.jpg" }));
  fireEvent.click(screen.getByRole("button", { name: "Person.png" }));
  fireEvent.click(screen.getByRole("button", { name: "Attach 2 files" }));
  expect(screen.getByAltText("Reference 1").getAttribute("src")).toBe(
    "/api/artifacts/outfit/file",
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Move reference 2 earlier" }),
  );
  expect(screen.getByAltText("Reference 1").getAttribute("src")).toBe(
    "/api/artifacts/person/file",
  );
  fireEvent.click(screen.getByRole("button", { name: "Voice from Library" }));
  fireEvent.click(await screen.findByRole("button", { name: "Voice.wav" }));
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
