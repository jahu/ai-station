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
            parameters: {},
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

it("shows speech playback with the existing voice/Avatar source actions", async () => {
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
            executor_type: "chatterbox",
            capability: "audio.speech",
            status: "succeeded",
            parameters: { text: "Dzień dobry." },
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
});
