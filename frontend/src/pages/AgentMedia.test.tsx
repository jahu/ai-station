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
