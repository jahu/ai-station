import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import MediaResult from "./MediaResult";
import type { Artifact, ArtifactLineage, Run } from "../../api";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const portrait: Artifact = {
  id: "portrait1",
  type: "image",
  mime_type: "image/png",
  original_filename: "portrait.png",
  title: "Portrait",
  size_bytes: 10,
  created_at: "2026-09-28T10:00:00Z",
  run_id: null,
  parent_artifact_ids: [],
  metadata: {},
};
const voice: Artifact = {
  ...portrait,
  id: "voiceclip",
  type: "audio",
  mime_type: "audio/wav",
  original_filename: "voice.wav",
  title: "Voice take",
};
const video: Artifact = {
  ...portrait,
  id: "avatar01",
  type: "video",
  mime_type: "video/mp4",
  original_filename: "avatar.mp4",
  title: "Avatar take",
  parent_artifact_ids: ["portrait1", "voiceclip"],
  metadata: { capability: "avatar.animate" },
};

function mount(run: Run, lineage: ArtifactLineage, artifact: Artifact) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      expect(init?.method ?? "GET").toBe("GET");
      const url = String(path);
      return {
        ok: true,
        json: async () =>
          url.endsWith("/lineage")
            ? lineage
            : url.includes("/artifacts?")
              ? [artifact]
              : run,
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
        <MediaResult
          kind={artifact.type === "audio" ? "audio" : "video"}
          runId={run.id}
          run={run}
          error={null}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("shows avatar sources in the workspace without inventing a Run", async () => {
  mount(
    { id: "done", status: "succeeded" } as Run,
    { id: "avatar01", sources: [portrait, voice], derived: [] },
    video,
  );
  const first = await screen.findByRole("link", {
    name: "Inspect source Portrait portrait",
  });
  const second = screen.getByRole("link", {
    name: "Inspect source Voice take voicecli",
  });
  expect(screen.getByText(/There is no inspectable lineage Run/)).toBeTruthy();
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  fireEvent.keyDown(first.closest(".lineage-strip") as HTMLElement, {
    key: "ArrowRight",
  });
  expect(second.tabIndex).toBe(0);
  expect(document.activeElement).toBe(second);
  expect(second.getAttribute("href")).toBe("/library/voiceclip");
});

it("shows speech source lineage beside the generated WAV", async () => {
  const speech: Artifact = {
    ...voice,
    id: "spoken01",
    title: "Spoken line",
    parent_artifact_ids: ["voiceclip"],
  };
  mount(
    { id: "speech", status: "succeeded" } as Run,
    { id: "spoken01", sources: [voice], derived: [] },
    speech,
  );
  const source = await screen.findByRole("link", {
    name: "Inspect source Voice take voicecli",
  });
  expect(source.getAttribute("href")).toBe("/library/voiceclip");
  expect(screen.getByLabelText("Generated audio")).toBeTruthy();
});
