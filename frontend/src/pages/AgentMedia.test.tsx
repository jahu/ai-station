import { useState } from "react";
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
import AgentMediaScopeEditor from "./AgentMediaScope";
import AgentMediaResult from "./AgentMediaResult";
import {
  agentMediaIssue,
  newAgentMedia,
  type AgentMediaScope,
} from "./agent-media";
import { activationBlock } from "./agentActivation";
import { agentSettingsPayload } from "./agentSettings";
import type { Run } from "../api";

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
function responses(artifacts: object[] = []) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => ({
      ok: true,
      json: async () =>
        path.includes("/hardware")
          ? { gpus: [{ index: 7, name: "Fixture GPU" }] }
          : path.endsWith("/lineage")
            ? { id: "track", sources: [], derived: [] }
            : artifacts,
    })),
  );
}

it("edits a frozen music policy and supplied lyrics without an automatic-duration option", () => {
  responses();
  function Editor() {
    const [value, setValue] = useState<AgentMediaScope>(
      newAgentMedia("music", "Warm acoustic folk"),
    );
    return (
      <>
        <AgentMediaScopeEditor
          value={value}
          goal="Warm acoustic folk"
          disabled={false}
          onChange={setValue}
          onBusy={() => {}}
        />
        <output aria-label="Media scope">{JSON.stringify(value)}</output>
      </>
    );
  }
  render(
    <Frame>
      <Editor />
    </Frame>,
  );
  fireEvent.change(screen.getByLabelText("Media description policy"), {
    target: { value: "fixed" },
  });
  fireEvent.change(screen.getByLabelText("Music length"), {
    target: { value: "60" },
  });
  expect(
    screen.queryByRole("option", { name: /From your message/ }),
  ).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "With lyrics" }));
  expect(screen.getByText("Add the lyrics for your song.")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Your lyrics"), {
    target: { value: "[Verse]\nMorning light" },
  });
  const scope = JSON.parse(
    screen.getByLabelText("Media scope").textContent || "{}",
  );
  expect(scope.request).toEqual(
    expect.objectContaining({
      duration_seconds: 60,
      instrumental: false,
      lyrics: "[Verse]\nMorning light",
    }),
  );
  expect(agentMediaIssue(scope)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Image" }));
  const image = JSON.parse(
    screen.getByLabelText("Media scope").textContent || "{}",
  );
  expect(image.kind).toBe("image");
  expect(image.description_source).toBe("fixed");
  expect(image.request.lyrics).toBeUndefined();
});

it("saves media authority, clears it when its tool is removed, and allows fixed output without a text model", () => {
  const scope: AgentMediaScope = {
    kind: "music",
    description_source: "fixed",
    request: {
      caption: "Calm piano",
      duration_seconds: 10,
      instrumental: true,
    },
  };
  const agent = {
    updated_at: "version",
    name: "Piano",
    goal: "Create piano music",
    model: "",
    tools: ["create_media"],
    media: scope,
    enabled: false,
  };
  expect(agentSettingsPayload(agent).media).toEqual(scope);
  expect(agentSettingsPayload(agent, { tools: [] }).media).toBeNull();
  expect(
    activationBlock(agent, [
      {
        name: "create_media",
        description: "Create media",
        operational: true,
        required_permissions: ["filesystem_read", "workspace_write"],
      },
    ]).blocked,
  ).toBe(false);
  const creative = {
    ...agent,
    media: { ...scope, description_source: "goal" as const },
  };
  expect(activationBlock(creative, []).reason).toContain(
    "Select a local model",
  );
});

it("shows the actual completed music inline with Library access and no speech or child-retry action", async () => {
  responses([
    {
      id: "track",
      type: "audio",
      mime_type: "audio/wav",
      title: "Quiet piano",
      relative_path: "artifacts/track.wav",
      original_filename: "track.wav",
      size_bytes: 1920044,
      run_id: "music",
      metadata: { capability: "audio.music", duration_seconds: 10 },
      created_at: "2026-10-23T10:00:00Z",
      parent_artifact_ids: [],
    },
  ]);
  render(
    <Frame>
      <AgentMediaResult
        runs={[
          {
            id: "music",
            task_id: "task",
            executor_type: "ace_step_music",
            capability: "audio.music",
            status: "succeeded",
            project_id: null,
            parent_run_id: null,
            execution_target: "host",
            created_at: "2026-10-23T10:00:00Z",
            started_at: "2026-10-23T10:00:00Z",
            finished_at: "2026-10-23T10:01:00Z",
            actual_gpu: "7",
            requested_gpu: "7",
            effective_permissions: ["filesystem_read", "workspace_write"],
            summary: "",
            error_type: "",
            worker_id: null,
            parameters: {
              instrumental: false,
              lyrics: "[Chorus]\nA bright new day",
            },
            metadata: {},
            error_message: "",
          } as Run,
        ]}
      />
    </Frame>,
  );
  await waitFor(() =>
    expect(screen.getByLabelText("Generated music").getAttribute("src")).toBe(
      "/api/artifacts/track/file",
    ),
  );
  expect(
    screen.getByRole("link", { name: "Open in Library" }).getAttribute("href"),
  ).toBe("/library/track");
  expect(
    screen.getByRole("region", { name: "Song lyrics" }).textContent,
  ).toContain("A bright new day");
  expect(screen.queryByRole("link", { name: /Use as speech/ })).toBeNull();
  expect(screen.queryByRole("button", { name: /Retry/ })).toBeNull();
});

it("checks the selected engine rather than another installed media kind", () => {
  const agent = {
    enabled: false,
    tools: ["create_media"],
    model: "",
    permission_profile: "agent_local",
    media: {
      ...newAgentMedia("music", "Piano"),
      description_source: "fixed" as const,
    },
  };
  const catalog = [
    {
      name: "create_media",
      description: "Create media",
      operational: true,
      required_permissions: [],
      outputs: {
        image: { ready: true, modes: ["t2i"] },
        music: { ready: false, reason: "Music setup is missing" },
      },
    },
  ];
  expect(activationBlock(agent, catalog)).toEqual({
    blocked: true,
    reason: "Music setup is missing",
  });
  expect(
    activationBlock(
      {
        ...agent,
        media: {
          ...newAgentMedia("image", "Forest"),
          description_source: "fixed" as const,
        },
      },
      catalog,
    ).blocked,
  ).toBe(false);
});

it("keeps Upscale tied to its fixed source instead of a text-model preparation", () => {
  expect(
    agentMediaIssue({
      kind: "image",
      description_source: "goal",
      request: {
        mode: "upscale",
        input_artifact_ids: ["reviewed-image"],
      },
    }),
  ).toContain("exact source image");
  expect(
    agentMediaIssue({
      kind: "image",
      description_source: "fixed",
      request: {
        mode: "upscale",
        input_artifact_ids: ["reviewed-image"],
      },
    }),
  ).toBeNull();
});

it("reviews a pending speech draft, selects and removes its Library voice without starting work", async () => {
  const id = "c23c77b2-e3d6-46ab-bc80-04108a4615c2";
  const voice = {
    id,
    type: "audio",
    mime_type: "audio/wav",
    title: "Polish reference",
    original_filename: "voice.wav",
    relative_path: "artifacts/voice.wav",
    size_bytes: 6400,
    metadata: { duration_seconds: 0.2 },
    parent_artifact_ids: [],
    created_at: "2026-10-23T10:00:00Z",
  };
  const fetch = vi.fn(async (url: string) => ({
    ok: true,
    json: async () =>
      url.includes("/hardware")
        ? { gpus: [{ index: 7, name: "Fixture GPU" }] }
        : url.endsWith("/" + id)
          ? voice
          : [voice],
  }));
  vi.stubGlobal("fetch", fetch);
  function Editor() {
    const [scope, setScope] = useState<AgentMediaScope>({
      ...newAgentMedia("speech", "Powiedz dzień dobry"),
      description_source: "fixed",
    });
    return (
      <>
        <AgentMediaScopeEditor
          value={scope}
          goal="Powiedz dzień dobry"
          disabled={false}
          onChange={setScope}
          onBusy={() => {}}
        />
        <output aria-label="Speech settings">{JSON.stringify(scope)}</output>
      </>
    );
  }
  render(
    <Frame>
      <Editor />
    </Frame>,
  );
  expect(
    screen.getByText(/Choose a voice reference from Library/),
  ).toBeTruthy();
  expect(
    (screen.getByLabelText("Media creative direction") as HTMLTextAreaElement)
      .maxLength,
  ).toBe(1000);
  fireEvent.click(screen.getByRole("button", { name: "Choose from Library" }));
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Choose Polish reference c23c77b2",
    }),
  );
  await waitFor(() =>
    expect(
      JSON.parse(screen.getByLabelText("Speech settings").textContent || "{}")
        .request.reference_artifact_id,
    ).toBe(id),
  );
  fireEvent.change(screen.getByLabelText("Media creative direction"), {
    target: { value: "Witaj w AI Station." },
  });
  const saved = JSON.parse(
    screen.getByLabelText("Speech settings").textContent || "{}",
  );
  expect(saved.request.reference_artifact_id).toBe(id);
  expect(agentMediaIssue(saved)).toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "Remove voice reference" }),
  );
  const pending = JSON.parse(
    screen.getByLabelText("Speech settings").textContent || "{}",
  );
  expect(pending.request.reference_artifact_id).toBeNull();
  expect(agentMediaIssue(pending)).toContain("before enabling");
  expect(agentMediaIssue(pending, { allowMissingVoice: true })).toBeNull();
  expect(fetch.mock.calls.every(([url]) => !url.includes("/runs"))).toBe(true);
});

it.each(["chatterbox", "fish_speech"])(
  "shows %s speech playback with the existing voice/Avatar source actions",
  async (executor) => {
    responses([
      {
        id: "speech",
        type: "audio",
        mime_type: "audio/wav",
        title: "Daily brief",
        original_filename: "brief.wav",
        relative_path: "artifacts/brief.wav",
        size_bytes: 9600,
        run_id: "speech-run",
        metadata: { capability: "audio.speech", duration_seconds: 0.2 },
        parent_artifact_ids: [],
        created_at: "2026-10-23T10:00:00Z",
      },
    ]);
    render(
      <Frame>
        <AgentMediaResult
          runs={[
            {
              id: "speech-run",
              task_id: "speech-task",
              project_id: null,
              parent_run_id: null,
              execution_target: "host",
              created_at: "2026-10-23T10:00:00Z",
              started_at: null,
              finished_at: null,
              actual_gpu: "7",
              requested_gpu: "auto",
              effective_permissions: ["filesystem_read", "workspace_write"],
              summary: "Speech generated",
              error_type: "",
              worker_id: null,
              executor_type: executor,
              capability: "audio.speech",
              status: "succeeded",
              parameters: {
                text: "Dzień dobry.",
                ...(executor === "fish_speech"
                  ? {
                      backend: "fish_s2_pro",
                      direction: "whisper",
                      pace: "slow",
                    }
                  : {}),
              },
              metadata: {},
              error_message: "",
            },
          ]}
        />
      </Frame>,
    );
    await waitFor(() =>
      expect(screen.getByLabelText("Generated audio")).toBeTruthy(),
    );
    expect(screen.getByRole("link", { name: "Open in Library" })).toBeTruthy();
    expect(screen.getByRole("link", { name: /^Use as speech/ })).toBeTruthy();
    if (executor === "fish_speech")
      expect(screen.getByText("Fish S2 Pro · Whisper")).toBeTruthy();
  },
);

it("edits full video timing and storyboard without exposing a receipt or short-clip frames", async () => {
  responses();
  function Editor() {
    const [value, setValue] = useState<AgentMediaScope>(
      newAgentMedia("video", "Quiet forest"),
    );
    return (
      <>
        <AgentMediaScopeEditor
          value={value}
          goal="Quiet forest"
          disabled={false}
          onChange={setValue}
          onBusy={() => {}}
        />
        <output aria-label="Media scope">{JSON.stringify(value)}</output>
      </>
    );
  }
  render(
    <Frame>
      <Editor />
    </Frame>,
  );
  expect(
    screen.getByRole("button", { name: "Video" }).getAttribute("aria-pressed"),
  ).toBe("true");
  fireEvent.change(screen.getByLabelText("Agent film length"), {
    target: { value: "30" },
  });
  fireEvent.change(screen.getByLabelText("Agent video motion"), {
    target: { value: "shots" },
  });
  fireEvent.click(
    screen.getByRole("checkbox", { name: "Plan individual scenes" }),
  );
  const description = screen.getByLabelText("Scene 1 prompt");
  fireEvent.change(description, { target: { value: "Green trees" } });
  const saved = JSON.parse(screen.getByLabelText("Media scope").textContent!);
  expect(saved.request.duration_seconds).toBe(30);
  expect(saved.request.scenes).toEqual([
    { prompt: "Green trees", duration_seconds: 30 },
  ]);
  expect(agentMediaIssue(saved)).toBeNull();
  expect(saved.request.frames).toBeUndefined();
  expect(saved.request.client_request_id).toBeUndefined();
  fireEvent.change(screen.getByLabelText("Agent video motion"), {
    target: { value: "continuous" },
  });
  expect(
    screen.queryByRole("checkbox", { name: "Plan individual scenes" }),
  ).toBeNull();
  expect(
    JSON.parse(screen.getByLabelText("Media scope").textContent!).request
      .scenes,
  ).toBeNull();
});

it("shows full agent film progress and the final artifact instead of a completed first segment", async () => {
  const writes: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      if (options?.method === "POST") writes.push(url);
      return {
        ok: true,
        json: async () =>
          url.includes("/media/jobs/")
            ? {
                task_id: "film-task",
                revision: 1,
                kind: "video",
                mode: "continuous",
                status: "succeeded",
                duration_seconds: 30,
                completed_segments: 9,
                total_segments: 9,
                active_run_ids: [],
                final_artifact_id: "full-film",
                resume_allowed: true,
                error_message: "",
              }
            : { id: "full-film", type: "video", mime_type: "video/mp4" },
      };
    }),
  );
  render(
    <Frame>
      <AgentMediaResult
        runs={[
          {
            id: "compose",
            task_id: "film-task",
            executor_type: "media_compose",
            status: "succeeded",
            parameters: {},
          } as Run,
          {
            id: "segment",
            task_id: "film-task",
            executor_type: "wan_video",
            status: "succeeded",
            parameters: {},
          } as Run,
        ]}
      />
    </Frame>,
  );
  const player = await screen.findByLabelText("Generated full video");
  expect(player.getAttribute("src")).toBe("/api/artifacts/full-film/file");
  expect(screen.getByText("Your full video is ready.")).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: "Resume unfinished work" }),
  ).toBeNull();
  expect(writes).toEqual([]);
});

it("keeps an avatar draft reviewable while awaiting sources and switches to complete recorded speech", () => {
  responses();
  function Editor() {
    const [value, setValue] = useState<AgentMediaScope>(
      newAgentMedia("avatar", "Welcome me in Polish"),
    );
    return (
      <>
        <AgentMediaScopeEditor
          value={value}
          goal="Welcome me in Polish"
          disabled={false}
          onChange={setValue}
          onBusy={() => {}}
        />
        <output aria-label="Media scope">{JSON.stringify(value)}</output>
      </>
    );
  }
  render(
    <Frame>
      <Editor />
    </Frame>,
  );
  let saved = JSON.parse(screen.getByLabelText("Media scope").textContent!);
  expect(agentMediaIssue(saved)).toMatch(/portrait and a WAV/);
  expect(agentMediaIssue(saved, { allowMissingSources: true })).toBeNull();
  expect(
    screen.getByRole("button", { name: "Avatar" }).getAttribute("aria-pressed"),
  ).toBe("true");
  fireEvent.change(screen.getByLabelText("Media creative direction"), {
    target: { value: "Dzień dobry." },
  });
  saved = JSON.parse(screen.getByLabelText("Media scope").textContent!);
  expect(saved.request.speech_text).toBe("Dzień dobry.");
  fireEvent.change(screen.getByLabelText("Agent avatar speech source"), {
    target: { value: "recording" },
  });
  saved = JSON.parse(screen.getByLabelText("Media scope").textContent!);
  expect(saved.request.speech_text).toBeNull();
  expect(screen.getByText(/Uses your entire saved recording/)).toBeTruthy();
  expect(saved.request.image_artifact_id).toBeNull();
  expect(saved.request.audio_artifact_id).toBeNull();
});

it("shows the whole avatar job and saved spoken words while its planner is pending", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      json: async () =>
        url.includes("/media/jobs/")
          ? {
              task_id: "avatar-task",
              revision: 1,
              kind: "avatar",
              mode: "continuous",
              status: "preparing",
              duration_seconds: null,
              completed_segments: 0,
              total_segments: 0,
              active_run_ids: ["planner"],
              final_artifact_id: null,
              resume_allowed: false,
              error_message: "",
            }
          : [],
    })),
  );
  render(
    <Frame>
      <AgentMediaResult
        runs={[
          {
            id: "planner",
            task_id: "avatar-task",
            executor_type: "avatar_media_plan",
            status: "queued",
            parameters: {},
          } as Run,
          {
            id: "speech",
            task_id: "avatar-task",
            executor_type: "chatterbox",
            status: "succeeded",
            parameters: { text: "Dzień dobry." },
            project_id: null,
            parent_run_id: null,
            capability: "audio.speech",
            execution_target: "host",
            created_at: "2026-10-23T00:00:00Z",
            started_at: null,
            finished_at: null,
            requested_gpu: "auto",
            actual_gpu: null,
            effective_permissions: ["filesystem_read", "workspace_write"],
            summary: "Ready",
            error_type: "",
            error_message: "",
            worker_id: null,
          } satisfies Run,
        ]}
      />
    </Frame>,
  );
  await screen.findByText("Your talking avatar");
  expect(
    screen.getByRole("region", { name: "Spoken text" }).textContent,
  ).toContain("Dzień dobry.");
  expect(screen.queryByLabelText("Generated full video")).toBeNull();
  expect(screen.queryByLabelText("Generated audio")).toBeNull();
});

it("requires speech readiness only when the avatar writes new words", () => {
  const scope = newAgentMedia("avatar", "Welcome");
  if (scope.kind !== "avatar") throw new Error("Expected avatar scope");
  const agent = {
    enabled: false,
    tools: ["create_media"],
    model: "",
    permission_profile: "agent_local",
    media: {
      ...scope,
      description_source: "fixed" as const,
      request: {
        ...scope.request,
        image_artifact_id: "portrait",
        audio_artifact_id: "voice",
      },
    },
  };
  const catalog = [
    {
      name: "create_media",
      description: "Create media",
      operational: true,
      required_permissions: [],
      outputs: { avatar: { ready: true, speech_ready: false } },
    },
  ];
  expect(activationBlock(agent, catalog).reason).toMatch(
    /Polish speech is unavailable/,
  );
  expect(
    activationBlock(
      {
        ...agent,
        media: {
          ...agent.media,
          request: { ...agent.media.request, speech_text: null },
        },
      },
      catalog,
    ).blocked,
  ).toBe(false);
});

it("offers original lyrics for goal-based vocals and clears that authority for fixed text or instrumental", () => {
  responses();
  function Editor() {
    const [value, setValue] = useState<AgentMediaScope>(
      newAgentMedia("music", "Write a short original Polish folk song"),
    );
    return (
      <>
        <AgentMediaScopeEditor
          value={value}
          goal="Write a short original Polish folk song"
          disabled={false}
          onChange={setValue}
          onBusy={() => {}}
        />
        <output aria-label="Lyric scope">{JSON.stringify(value)}</output>
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
  const current = () =>
    JSON.parse(screen.getByLabelText("Lyric scope").textContent || "{}");
  expect(agentMediaIssue(current())).toBeNull();
  expect(
    agentSettingsPayload({
      name: "Song",
      updated_at: "version",
      media: current(),
      tools: ["create_media"],
    }).media,
  ).toEqual(expect.objectContaining({ lyrics_source: "goal" }));
  fireEvent.change(screen.getByLabelText("Song lyrics policy"), {
    target: { value: "fixed" },
  });
  expect(screen.getByText("Add the lyrics for your song.")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Your lyrics"), {
    target: { value: "[Verse]\nReviewed words" },
  });
  fireEvent.change(screen.getByLabelText("Song lyrics policy"), {
    target: { value: "goal" },
  });
  expect(
    (screen.getByLabelText("Lyrics guidance (optional)") as HTMLTextAreaElement)
      .value,
  ).toContain("Reviewed words");
  fireEvent.change(screen.getByLabelText("Media description policy"), {
    target: { value: "fixed" },
  });
  expect(current().lyrics_source).toBe("fixed");
  expect(screen.queryByLabelText("Song lyrics policy")).toBeNull();
  expect(screen.getByLabelText("Your lyrics")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Instrumental" }));
  expect(current().lyrics_source).toBe("fixed");
  expect(current().request.lyrics).toBe("");
  expect(screen.queryByLabelText("Your lyrics")).toBeNull();
});

it("rejects generated lyric authority outside a goal-based vocal scope", () => {
  const base = {
    ...newAgentMedia("music", "Folk"),
    kind: "music" as const,
    description_source: "goal" as const,
    lyrics_source: "goal" as const,
    request: {
      caption: "Folk",
      instrumental: false,
      lyrics: "",
      duration_seconds: 30,
    },
  };
  expect(agentMediaIssue(base)).toBeNull();
  expect(agentMediaIssue({ ...base, description_source: "fixed" })).toContain(
    "goal-based",
  );
  expect(
    agentMediaIssue({
      ...base,
      request: { ...base.request, instrumental: true },
    }),
  ).toContain("vocals");
});

it("reviews expressive speech direction separately from exact words and clears controls on model switches", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      json: async () =>
        url.endsWith("/audio/capabilities")
          ? {
              available: false,
              engines: { fish_s2_pro: { available: true, readiness: "ready" } },
            }
          : url.includes("/hardware")
            ? { gpus: [] }
            : [],
    })),
  );
  function Editor() {
    const [value, setValue] = useState<AgentMediaScope>({
      kind: "speech",
      description_source: "fixed",
      request: {
        text: "Dokładne słowa.",
        reference_artifact_id: "c23c77b2-e3d6-46ab-bc80-04108a4615c2",
        delivery: { exaggeration: 1, cfg_weight: 0.4, temperature: 0.6 },
      },
    });
    return (
      <>
        <AgentMediaScopeEditor
          value={value}
          goal="Speak"
          disabled={false}
          onChange={setValue}
          onBusy={() => {}}
          readiness={{
            speech: { ready: false, reason: "Chatterbox unavailable" },
          }}
        />
        <output aria-label="Reviewed speech">{JSON.stringify(value)}</output>
      </>
    );
  }
  render(
    <Frame>
      <Editor />
    </Frame>,
  );
  await waitFor(() =>
    expect(
      screen
        .getByRole("option", { name: "Fish S2 Pro · Expressive" })
        .hasAttribute("disabled"),
    ).toBe(false),
  );
  fireEvent.change(screen.getByLabelText("Speech model"), {
    target: { value: "fish_s2_pro" },
  });
  fireEvent.change(screen.getByLabelText("Voice direction"), {
    target: { value: "whisper" },
  });
  fireEvent.change(screen.getByLabelText("Speaking pace"), {
    target: { value: "slow" },
  });
  let saved = JSON.parse(
    screen.getByLabelText("Reviewed speech").textContent || "{}",
  );
  expect(saved.request).toMatchObject({
    engine: "fish_s2_pro",
    direction: "whisper",
    pace: "slow",
    text: "Dokładne słowa.",
  });
  expect(saved.request.delivery).toBeUndefined();
  const agent = {
    enabled: false,
    name: "Narrator",
    goal: "Speak",
    tools: ["create_media"],
    media: saved,
  };
  const catalog = [
    {
      name: "create_media",
      description: "Create",
      operational: true,
      required_permissions: [],
      outputs: {
        speech: { ready: false, engines: { fish_s2_pro: { ready: true } } },
      },
    },
  ];
  expect(activationBlock(agent, catalog).blocked).toBe(false);
  catalog[0].outputs.speech.engines.fish_s2_pro.ready = false;
  expect(activationBlock(agent, catalog).blocked).toBe(true);
  expect(screen.queryByText(/Chatterbox unavailable/)).toBeNull();
  expect(
    agentSettingsPayload({
      updated_at: "reviewed-version",
      name: "Narrator",
      goal: "Speak",
      tools: ["create_media"],
      media: saved,
    }).media,
  ).toEqual(saved);
  fireEvent.change(screen.getByLabelText("Speech model"), {
    target: { value: "" },
  });
  saved = JSON.parse(
    screen.getByLabelText("Reviewed speech").textContent || "{}",
  );
  expect(saved.request.engine).toBeUndefined();
  expect(saved.request.direction).toBeUndefined();
  expect(saved.request.pace).toBeUndefined();
  expect(saved.request.text).toBe("Dokładne słowa.");
  expect(screen.queryByLabelText("Voice direction")).toBeNull();
});

it("reviews a Library film and exact scene sounds for a local effects agent", async () => {
  const film = {
    id: "11111111-1111-4111-8111-111111111111",
    type: "video",
    mime_type: "video/mp4",
    original_filename: "Quiet garden.mp4",
    metadata: { frames: 72, fps: 24, width: 1280, height: 704 },
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => ({
      ok: true,
      json: async () =>
        path.endsWith("/audio/effects/capabilities")
          ? { available: true }
          : path.includes("/hardware")
            ? { gpus: [] }
            : path === "/api/artifacts"
              ? [film]
              : path === "/api/artifacts/" + film.id
                ? film
                : [],
    })),
  );
  function Editor() {
    const [value, setValue] = useState<AgentMediaScope>(
      newAgentMedia("effects", "Wind in the trees"),
    );
    return (
      <>
        <AgentMediaScopeEditor
          value={value}
          goal="Wind in the trees"
          disabled={false}
          onChange={setValue}
          onBusy={() => {}}
        />
        <output aria-label="Media scope">{JSON.stringify(value)}</output>
      </>
    );
  }
  render(
    <Frame>
      <Editor />
    </Frame>,
  );
  expect(screen.queryByLabelText("Upload speech")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Choose from Library" }));
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Choose Quiet garden.mp4 11111111",
    }),
  );
  await waitFor(() =>
    expect(screen.getByLabelText("Agent source film preview")).toBeTruthy(),
  );
  fireEvent.click(
    screen.getByText("Change sounds over time", { exact: false }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Add scene direction" }));
  fireEvent.change(screen.getByLabelText("Scene 1 sound description"), {
    target: { value: "A bird calls in the trees" },
  });
  const saved = JSON.parse(screen.getByLabelText("Media scope").textContent!);
  expect(saved.kind).toBe("effects");
  expect(saved.request.video_artifact_id).toBe(film.id);
  expect(saved.request.prompt).toBe("Wind in the trees");
  expect(saved.request.cues).toEqual([
    { start_frame: 0, end_frame: 72, prompt: "A bird calls in the trees" },
  ]);
  expect(agentMediaIssue(saved)).toBeNull();
  expect(
    agentMediaIssue({
      ...saved,
      request: { ...saved.request, video_artifact_id: null },
    }),
  ).toMatch(/Choose a film/);
});
