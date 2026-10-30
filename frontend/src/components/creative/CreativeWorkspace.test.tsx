import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { AccountContext } from "../../account-context";
import {
  activateStorageAccount,
  clearPrivateBrowserState,
} from "../../lib/account-storage";
import Images from "../../pages/Images";
import Video from "../../pages/Video";
import Avatars from "../../pages/Avatars";
import Audio from "../../pages/Audio";
import CreativeWorkspace from "./CreativeWorkspace";
import type {
  CreativeCapability,
  CreativeDetail,
  CreativeTurn,
} from "./creative-context";
import type { Artifact, Run } from "../../api";

afterEach(() => {
  cleanup();
  clearPrivateBrowserState();
  vi.unstubAllGlobals();
});
const base: CreativeDetail = {
  id: "workspace-one",
  capability: "images",
  title: "Mountain retreat",
  draft: {},
  version: 1,
  created_at: "2026-10-30T10:00:00Z",
  updated_at: "2026-10-30T10:00:00Z",
  archived_at: null,
  turns: [],
  next_before: null,
};
const image = {
  size_bytes: 128,
  created_at: base.created_at,
  run_id: "run-one",
  id: "result-image",
  type: "image",
  mime_type: "image/png",
  original_filename: "retreat.png",
  parent_artifact_ids: [],
  metadata: { width: 768, height: 1024 },
} as Artifact;
const run = {
  id: "run-one",
  task_id: "task-one",
  parameters: {},
  status: "succeeded",
  capability: "image.generate",
  executor_type: "photo_pipe",
  requested_gpu: "auto",
  metadata: {},
  error_message: "",
} as Run;
const result = {
  id: "turn-one",
  run_id: run.id,
  task_id: run.task_id,
  parent_turn_id: null,
  position: 1,
  parameters: {
    mode: "t2i",
    backend: "qwen",
    prompt: "A quiet retreat",
    gpu: "auto",
  },
  created_at: base.created_at,
  feedback: "",
  run,
  artifacts: [image],
} as CreativeTurn;

function fixture(
  initial: Partial<CreativeDetail> = {},
  loseFirstResponse = false,
) {
  const state: CreativeDetail = structuredClone({ ...base, ...initial });
  const submissions: Record<string, unknown>[] = [];
  const receipts = new Map<string, CreativeTurn>();
  let lost = false;
  const fetch = vi.fn(
    async (input: RequestInfo | URL, options?: RequestInit) => {
      const path = String(input);
      const reply = (body: unknown, status = 200) =>
        new Response(JSON.stringify(body), {
          status,
          headers: { "Content-Type": "application/json" },
        });
      if (path === "/api/images/models")
        return reply({
          items: [
            {
              id: "qwen",
              definition_id: null,
              name: "Qwen Image",
              backend: "qwen",
              available: true,
              modes: ["t2i", "img2img", "recompose"],
              maximum_references: 8,
            },
          ],
          defaults: {
            revision: 0,
            choices: { t2i: "qwen", img2img: "qwen", recompose: "qwen" },
          },
        });
      if (path.includes("/system/hardware")) return reply({ gpus: [] });
      if (path.endsWith("/whole-capabilities"))
        return reply({ available: true, backend: "sonic", readiness: "ready" });
      if (
        path.endsWith("/capabilities") ||
        path.endsWith("/whole-capabilities")
      )
        return reply({
          available: true,
          readiness: "ready",
          max_seconds: 600,
          memory_profiles: [],
        });
      if (path.startsWith("/api/artifacts/voice-reference"))
        return reply({
          ...image,
          id: "voice-reference",
          type: "audio",
          mime_type: "audio/wav",
          metadata: { duration_seconds: 2, sample_rate: 24000, channels: 1 },
        });
      if (path === "/api/artifacts/result-image") return reply(image);
      if (path === "/api/media/jobs/task-one")
        return reply(state.turns.at(-1)?.job);
      if (path === "/api/runs/run-one") return reply(run);
      if (path === "/api/runs/translation-prep")
        return reply({ ...run, id: "translation-prep" });
      if (path === "/api/runs/translation-review")
        return reply({
          ...run,
          id: "translation-review",
          status: "waiting_for_approval",
          parameters: { effective: { prompt: "A red bicycle" } },
          approval: { payload: { effective_hash: "reviewed-prompt-hash" } },
        });
      if (path === "/api/generation/translations/translation-review/review")
        return reply({ status: "succeeded" });
      if (path.startsWith("/api/creative/sessions?")) return reply([state]);
      if (
        path === "/api/creative/sessions/workspace-one" &&
        options?.method === "PATCH"
      ) {
        const body = JSON.parse(String(options.body));
        if (body.expected_version !== state.version)
          return reply(
            { detail: "Workspace changed. Reload before saving." },
            409,
          );
        if (body.draft) state.draft = body.draft;
        if (body.title) state.title = body.title;
        if (body.archived !== undefined)
          state.archived_at = body.archived ? base.created_at : null;
        state.version++;
        return reply(state);
      }
      if (path === "/api/creative/sessions/workspace-one") return reply(state);
      if (path.endsWith("/generate")) {
        const body = JSON.parse(String(options?.body)) as Record<
          string,
          unknown
        >;
        submissions.push(body);
        const key = String(body.client_request_id);
        if (!receipts.has(key)) {
          const turn = structuredClone({
            ...result,
            id: `turn-${receipts.size + 1}`,
            position: state.turns.length + 1,
            parameters: body.parameters,
            feedback: body.feedback,
            parent_turn_id: body.parent_turn_id ?? null,
          }) as CreativeTurn;
          receipts.set(key, turn);
          if (body.request_kind === "job") {
            turn.request_kind = "job";
            turn.status = "queued";
            turn.job = {
              task_id: "task-one",
              revision: 1,
              kind: state.capability === "video" ? "video" : "avatar",
              mode: "continuous",
              status: "queued",
              duration_seconds: 15,
              completed_segments: 0,
              total_segments: 5,
              active_run_ids: [],
              final_artifact_id: null,
              resume_allowed: false,
              error_message: "",
              request: body.parameters as object,
            };
          }
          state.turns.push(turn);
          state.draft = body.parameters as Record<string, unknown>;
          state.version++;
        }
        if (loseFirstResponse && !lost) {
          lost = true;
          throw new Error("Connection lost after enqueue");
        }
        return reply(receipts.get(key), 202);
      }
      throw new Error("Unexpected creative UI request: " + path);
    },
  );
  vi.stubGlobal("fetch", fetch);
  return { state, submissions, fetch };
}

function mount(capability: CreativeCapability = "images") {
  activateStorageAccount("account-one");
  const cache = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 60_000 },
      mutations: { retry: false },
    },
  });
  render(
    <AccountContext.Provider
      value={{
        mode: "accounts",
        user: {
          id: "account-one",
          username: "Alice",
          display_name: "Alice",
          enabled: true,
          is_admin: false,
          mfa_enabled: false,
          created_at: base.created_at,
        },
      }}
    >
      <QueryClientProvider client={cache}>
        <MemoryRouter
          initialEntries={[
            `${capability === "music" || capability === "speech" ? "/audio" : "/" + capability}?session=workspace-one${capability === "music" ? "&mode=music" : ""}`,
          ]}
        >
          <Link to="/elsewhere">Leave workspace</Link>
          <Routes>
            <Route
              path="/images"
              element={
                <CreativeWorkspace capability="images">
                  <Images />
                </CreativeWorkspace>
              }
            />
            <Route path="/video" element={<Video withCreativeSessions />} />
            <Route
              path="/avatars"
              element={
                <CreativeWorkspace capability="avatars">
                  <Avatars />
                </CreativeWorkspace>
              }
            />
            <Route path="/audio" element={<Audio withCreativeSessions />} />
            <Route
              path="/elsewhere"
              element={
                <Link to="/images?session=workspace-one">Return to images</Link>
              }
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </AccountContext.Provider>,
  );
}

it("flushes a private draft when navigating away and restores the same form", async () => {
  const backend = fixture();
  mount();
  fireEvent.change(await screen.findByLabelText("Prompt"), {
    target: { value: "A lakeside retreat at sunrise" },
  });
  fireEvent.click(screen.getByRole("link", { name: "Leave workspace" }));
  await waitFor(() =>
    expect(
      (backend.state.draft.formState as Record<string, unknown>).prompt,
    ).toBe("A lakeside retreat at sunrise"),
  );
  expect(
    backend.fetch.mock.calls.some(([, options]) => options?.keepalive),
  ).toBe(true);
  fireEvent.click(screen.getByRole("link", { name: "Return to images" }));
  expect(
    ((await screen.findByLabelText("Prompt")) as HTMLTextAreaElement).value,
  ).toBe("A lakeside retreat at sunrise");
  const patch = backend.fetch.mock.calls.find(
    ([, options]) => options?.method === "PATCH",
  );
  expect(new Headers(patch?.[1]?.headers).get("X-AI-Station-Account")).toBe(
    "account-one",
  );
});

it("shows the artifact history and uses the exact selected image for an edit", async () => {
  const backend = fixture({ turns: [result] });
  mount();
  expect(
    (await screen.findByRole("img", { name: "Generated image" })).getAttribute(
      "src",
    ),
  ).toBe("/api/artifacts/result-image/file");
  expect(screen.queryByLabelText("Edit instruction")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Edit this image" }));
  fireEvent.change(await screen.findByLabelText("Edit instruction"), {
    target: { value: "Give the landscape warmer sunlight" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Queue edit" }));
  await waitFor(() => expect(backend.submissions).toHaveLength(1));
  expect(backend.submissions[0]).toMatchObject({
    parent_turn_id: "turn-one",
    parameters: {
      mode: "img2img",
      input_artifact_ids: ["result-image"],
      edit_prompt: "Give the landscape warmer sunlight",
    },
  });
});

it("retains translation review controls inside the saved workspace", async () => {
  const backend = fixture({
    turns: [
      {
        ...result,
        status: "waiting_for_approval",
        artifacts: [],
        run: {
          ...run,
          status: "queued",
          metadata: {
            prompt_translation: {
              status: "waiting_for_review",
              preparation_run_id: "translation-prep",
              review_run_id: "translation-review",
              original: { prompt: "Czerwony rower" },
              effective: { prompt: "A red bicycle" },
              policy: { model: "local-translator", target_language: "en" },
            },
          },
        },
      },
    ],
  });
  mount();
  fireEvent.change(await screen.findByLabelText("Translated prompt"), {
    target: { value: "A red bicycle near a garden" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Use translated prompt" }),
  );
  await waitFor(() => {
    const request = backend.fetch.mock.calls.find(([path]) =>
      String(path).endsWith("/translation-review/review"),
    );
    expect(JSON.parse(String(request?.[1]?.body))).toEqual({
      expected_hash: "reviewed-prompt-hash",
      effective: { prompt: "A red bicycle near a garden" },
    });
  });
  expect(backend.submissions).toHaveLength(0);
});

it("restores a generation prompt when canonical edit_prompt is empty", async () => {
  fixture({
    turns: [
      { ...result, parameters: { ...result.parameters, edit_prompt: "" } },
    ],
  });
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Use these settings" }),
  );
  expect(
    ((await screen.findByLabelText("Prompt")) as HTMLTextAreaElement).value,
  ).toBe("A quiet retreat");
});

it("refreshes a fresh query cache after generation before naming the workspace", async () => {
  const backend = fixture({ title: "Untitled image" });
  mount();
  fireEvent.change(await screen.findByLabelText("Prompt"), {
    target: { value: "A quiet retreat" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Queue generate" }));
  expect(
    await screen.findByRole("img", { name: "Generated image" }),
  ).not.toBeNull();
  await waitFor(() => expect(backend.state.title).toBe("A quiet retreat"));
  expect(
    (screen.getByLabelText("Workspace name") as HTMLInputElement).value,
  ).toBe("A quiet retreat");
  expect(
    screen.queryByText("Workspace changed. Reload before saving."),
  ).toBeNull();
});

it("retries a lost submission response with the same receipt and preserves one version", async () => {
  const backend = fixture({}, true);
  mount();
  fireEvent.change(await screen.findByLabelText("Prompt"), {
    target: { value: "A quiet retreat" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Queue generate" }));
  expect(
    await screen.findByText("Connection lost after enqueue"),
  ).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Queue generate" }));
  await waitFor(() => expect(backend.submissions).toHaveLength(2));
  expect(backend.submissions[0].client_request_id).toBe(
    backend.submissions[1].client_request_id,
  );
  expect(backend.state.turns).toHaveLength(1);
});

it("restores archived workspaces without discarding their versions", async () => {
  const backend = fixture({ archived_at: base.created_at, turns: [result] });
  mount();
  expect(
    await screen.findByText(
      "This workspace is archived. Its history and results are retained.",
    ),
  ).not.toBeNull();
  expect(
    screen.queryByRole("button", { name: "Create next version" }),
  ).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Restore to continue" }));
  await waitFor(() => expect(backend.state.archived_at).toBeNull());
  expect(backend.state.turns).toHaveLength(1);
});

it("restores music lyrics and submits them without rewriting", async () => {
  const backend = fixture({
    capability: "music",
    draft: {
      formState: {
        caption: "A warm acoustic ballad",
        lyrics: "[Verse]\nDokładny tekst piosenki.",
        instrumental: false,
        duration: 30,
        seed: "",
        gpu: "auto",
      },
    },
  });
  mount("music");
  fireEvent.click(
    await screen.findByRole("button", { name: "Generate music" }),
  );
  await waitFor(() => expect(backend.submissions).toHaveLength(1));
  expect(backend.submissions[0].parameters).toMatchObject({
    caption: "A warm acoustic ballad",
    lyrics: "[Verse]\nDokładny tekst piosenki.",
    duration_seconds: 30,
    seed: null,
  });
});

it("restores the exact narration and reference voice", async () => {
  const backend = fixture({
    capability: "speech",
    draft: {
      formState: {
        text: "Dzień dobry. To jest dokładny tekst.",
        reference: "voice-reference",
        gpu: "auto",
      },
    },
  });
  mount("speech");
  fireEvent.click(
    await screen.findByRole("button", { name: "Generate speech" }),
  );
  await waitFor(() => expect(backend.submissions).toHaveLength(1));
  expect(backend.submissions[0].parameters).toEqual({
    text: "Dzień dobry. To jest dokładny tekst.",
    reference_artifact_id: "voice-reference",
    gpu: "auto",
  });
});

it("keeps long video generation as a full media job", async () => {
  const backend = fixture({
    capability: "video",
    draft: {
      formState: {
        prompt: "A slow mountain sunrise",
        duration: "15s",
        resolution: "1280x704",
        steps: 20,
        compositionMode: "continuous",
        gpu: "auto",
      },
    },
  });
  mount("video");
  const submit = await screen.findByRole("button", { name: "Generate video" });
  await waitFor(() =>
    expect((submit as HTMLButtonElement).disabled).toBe(false),
  );
  fireEvent.click(submit);
  await waitFor(() => expect(backend.submissions).toHaveLength(1));
  expect(backend.submissions[0]).toMatchObject({
    request_kind: "job",
    parameters: {
      prompt: "A slow mountain sunrise",
      duration_seconds: 15,
      composition_mode: "continuous",
    },
  });
});

it("retains the whole Sonic profile and exact script for an avatar continuation", async () => {
  const backend = fixture({
    capability: "avatars",
    draft: {
      formState: {
        image: "result-image",
        audio: "voice-reference",
        voiceMode: "text",
        speechText: "Dokładny tekst awatara.",
        fullRecording: true,
        wholeRecording: true,
        gpu: "auto",
      },
    },
  });
  mount("avatars");
  const submit = await screen.findByRole("button", {
    name: "Generate avatar video",
  });
  await waitFor(() =>
    expect((submit as HTMLButtonElement).disabled).toBe(false),
  );
  fireEvent.click(submit);
  await waitFor(() => expect(backend.submissions).toHaveLength(1));
  expect(backend.submissions[0]).toMatchObject({
    request_kind: "job",
    parameters: {
      generation_profile: "sonic_whole_768_v1",
      image_artifact_id: "result-image",
      audio_artifact_id: "voice-reference",
      speech_text: "Dokładny tekst awatara.",
    },
  });
  expect(
    (backend.submissions[0].parameters as Record<string, unknown>).size,
  ).toBeUndefined();
});
