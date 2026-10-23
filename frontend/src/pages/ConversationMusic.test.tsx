import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import AssistantActions, { AssistantResults } from "./AssistantActions";
import { emptyOptions } from "./assistant-options";
import { musicScopeReady } from "./music-scope";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

function setup() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => ({
      ok: true,
      json: async () =>
        path.includes("/hardware")
          ? { gpus: [{ index: 7, name: "Fixture GPU" }] }
          : path.endsWith("/lineage")
            ? { id: "music", sources: [], derived: [] }
            : [],
    })),
  );
}

it("selects music in Chat, keeps its typed controls, and clears scope when returning to conversation", () => {
  setup();
  function Editor() {
    const [value, setValue] = useState(emptyOptions);
    return (
      <>
        <AssistantActions
          value={value}
          onChange={setValue}
          busy={false}
          onUploading={() => {}}
          allowWork={false}
          description="Warm acoustic folk"
        />
        <output aria-label="Selected scope">{JSON.stringify(value)}</output>
      </>
    );
  }
  render(
    <Frame>
      <Editor />
    </Frame>,
  );
  fireEvent.change(screen.getByRole("combobox", { name: "Action" }), {
    target: { value: "audio.music" },
  });
  expect(screen.getByRole("region", { name: "Music settings" })).toBeTruthy();
  expect(screen.queryByLabelText("Image references")).toBeNull();
  fireEvent.change(screen.getByLabelText("Music length"), {
    target: { value: "120" },
  });
  fireEvent.click(screen.getByRole("button", { name: "With lyrics" }));
  fireEvent.change(screen.getByLabelText("Song lyrics policy"), {
    target: { value: "fixed" },
  });
  fireEvent.change(screen.getByLabelText("Your lyrics"), {
    target: { value: "[Verse]\nQuiet morning" },
  });
  let selected = JSON.parse(
    screen.getByLabelText("Selected scope").textContent || "{}",
  );
  expect(selected.music).toEqual(
    expect.objectContaining({
      duration_seconds: 120,
      instrumental: false,
      lyrics: "[Verse]\nQuiet morning",
    }),
  );
  expect(musicScopeReady(selected, "Warm acoustic folk")).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Instrumental" }));
  selected = JSON.parse(
    screen.getByLabelText("Selected scope").textContent || "{}",
  );
  expect(selected.music.lyrics).toBe("");
  fireEvent.click(screen.getByRole("button", { name: "With lyrics" }));
  expect(
    (screen.getByLabelText("Your lyrics") as HTMLTextAreaElement).value,
  ).toBe("[Verse]\nQuiet morning");
  fireEvent.change(screen.getByRole("combobox", { name: "Action" }), {
    target: { value: "chat" },
  });
  selected = JSON.parse(
    screen.getByLabelText("Selected scope").textContent || "{}",
  );
  expect(selected.music).toBeNull();
  expect(screen.queryByRole("region", { name: "Music settings" })).toBeNull();
});

it("keeps invalid music drafts unsent and explains an overlong description", () => {
  setup();
  render(
    <Frame>
      <AssistantActions
        value={{ ...emptyOptions, action: "audio.music", music: {} }}
        onChange={() => {}}
        busy={false}
        onUploading={() => {}}
        description={"x".repeat(513)}
      />
    </Frame>,
  );
  expect(screen.getByRole("alert").textContent).toContain("512");
  expect(
    musicScopeReady(
      { action: "audio.music", music: { instrumental: false, lyrics: "" } },
      "Piano",
    ),
  ).toBe(false);
  expect(
    musicScopeReady(
      { action: "audio.music", music: { duration_seconds: 601 } },
      "Piano",
    ),
  ).toBe(false);
  expect(
    musicScopeReady({ action: "audio.music", music: { seed: -1 } }, "Piano"),
  ).toBe(false);
  expect(musicScopeReady({ action: "audio.music" }, "x".repeat(513))).toBe(
    false,
  );
  expect(musicScopeReady({ action: "chat" }, "Regular conversation")).toBe(
    true,
  );
});

it("plays a music artifact inline with its library link and the correct accessible label", () => {
  setup();
  render(
    <Frame>
      <AssistantResults
        onUse={() => {}}
        result={{
          task_status: "succeeded",
          steps: [
            {
              id: "music-run",
              capability: "audio.music",
              status: "succeeded",
              summary: "",
              error_message: "",
              location: "local",
            },
          ],
          artifacts: [
            {
              id: "prep",
              type: "json",
              mime_type: "application/json",
              original_filename: "song-preparation.json",
              title: "",
              size_bytes: 50,
              created_at: "2026-10-23T06:00:00Z",
              run_id: "parent",
              parent_artifact_ids: [],
              metadata: { song_preparation: true },
            },
            {
              id: "music",
              type: "audio",
              mime_type: "audio/wav",
              original_filename: "track.wav",
              title: "Quiet piano",
              size_bytes: 1920044,
              created_at: "2026-10-23T06:00:00Z",
              run_id: "music-run",
              parent_artifact_ids: [],
              metadata: {
                capability: "audio.music",
                duration_seconds: 10,
                lyrics: "[Chorus]\nA bright new day",
              },
            },
          ],
        }}
      />
    </Frame>,
  );
  expect(
    screen.getByRole("region", { name: "Song lyrics music" }).textContent,
  ).toContain("A bright new day");
  expect(
    screen.queryByRole("link", { name: "song-preparation.json" }),
  ).toBeNull();
  expect(screen.getByLabelText("Generated music").getAttribute("src")).toBe(
    "/api/artifacts/music/file",
  );
  expect(
    screen.getByRole("link", { name: "Quiet piano" }).getAttribute("href"),
  ).toContain("/library/music");
  expect(
    screen.queryByRole("button", { name: "Use as voice reference" }),
  ).toBeNull();
  expect(screen.queryByRole("link", { name: /^Use as speech/ })).toBeNull();
  expect(screen.queryByRole("link", { name: /^Use in Audio/ })).toBeNull();
});

it("writes original lyrics without supplied words only in the selected vocal mode", () => {
  setup();
  function Editor() {
    const [value, setValue] = useState({
      ...emptyOptions,
      action: "audio.music" as const,
      music: {},
    });
    return (
      <>
        <AssistantActions
          value={value}
          onChange={(next) => setValue(next as typeof value)}
          busy={false}
          onUploading={() => {}}
          allowWork={false}
          description={"x".repeat(600)}
        />
        <output aria-label="Song scope">{JSON.stringify(value)}</output>
      </>
    );
  }
  render(
    <Frame>
      <Editor />
    </Frame>,
  );
  fireEvent.click(screen.getByRole("button", { name: "With lyrics" }));
  expect(
    (screen.getByLabelText("Song lyrics policy") as HTMLSelectElement).value,
  ).toBe("goal");
  expect(screen.getByLabelText("Lyrics guidance (optional)")).toBeTruthy();
  let selected = JSON.parse(
    screen.getByLabelText("Song scope").textContent || "{}",
  );
  expect(musicScopeReady(selected, "x".repeat(600))).toBe(true);
  expect(screen.queryByRole("alert")).toBeNull();
  fireEvent.change(screen.getByLabelText("Song lyrics policy"), {
    target: { value: "fixed" },
  });
  selected = JSON.parse(
    screen.getByLabelText("Song scope").textContent || "{}",
  );
  expect(musicScopeReady(selected, "Piano")).toBe(false);
  expect(screen.getByLabelText("Your lyrics")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Instrumental" }));
  selected = JSON.parse(
    screen.getByLabelText("Song scope").textContent || "{}",
  );
  expect(selected.music.lyrics_source).toBe("fixed");
  expect(screen.queryByLabelText("Song lyrics policy")).toBeNull();
});
