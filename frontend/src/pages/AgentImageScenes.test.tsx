import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import AgentMediaScopeEditor from "./AgentMediaScope";
import AgentMediaResult from "./AgentMediaResult";
import {
  agentMediaIssue,
  syncImageBrief,
  type AgentMediaScope,
} from "./agent-media";
import type { Run } from "../api";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const brief = "Keep the same person, vary the pose, setting and expression";
const initial: AgentMediaScope = {
  kind: "image",
  description_source: "goal",
  request: { mode: "img2img", edit_prompt: brief, input_artifact_ids: [""] },
};
function Frame({ children }: { children: React.ReactNode }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => ({
      ok: true,
      json: async () =>
        path.includes("/hardware") ? { gpus: [{ index: 7 }] } : [],
    })),
  );
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
function Editor() {
  const [scope, setScope] = useState(initial);
  return (
    <>
      <AgentMediaScopeEditor
        value={scope}
        goal={brief}
        disabled={false}
        onBusy={() => {}}
        onChange={setScope}
      />
      <output aria-label="Saved scope">{JSON.stringify(scope)}</output>
    </>
  );
}
function saved() {
  return JSON.parse(
    screen.getByLabelText("Saved scope").textContent!,
  ) as AgentMediaScope;
}

it("explains why small edits preserve composition and switches to reviewed new-scene planning explicitly", () => {
  render(
    <Frame>
      <Editor />
    </Frame>,
  );
  expect(screen.getByText("Want a new composition or setting?")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Use variations" }));
  const scope = saved();
  expect(scope.kind === "image" && scope.vary_scenes).toBe(true);
  expect(scope.request).toMatchObject({
    mode: "recompose",
    prompt_style: "instruction",
    input_artifact_ids: [""],
  });
  expect(
    screen.getByRole("checkbox", { name: /Vary results between runs/ }),
  ).toBeTruthy();
  expect(screen.queryByText("Want a new composition or setting?")).toBeNull();
  expect(
    (screen.getByLabelText("Media creative direction") as HTMLTextAreaElement)
      .value,
  ).toBe("");
  expect(
    vi
      .mocked(fetch)
      .mock.calls.some(([, options]) => options?.method === "POST"),
  ).toBe(false);
});

it("turns off planning when the user chooses an exact prompt and retains the identity reference", () => {
  render(
    <Frame>
      <Editor />
    </Frame>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Use variations" }));
  fireEvent.change(screen.getByLabelText("Media description policy"), {
    target: { value: "fixed" },
  });
  const scope = saved();
  expect(scope.kind === "image" && scope.vary_scenes).toBe(false);
  expect(scope.description_source).toBe("fixed");
  expect(scope.request).toMatchObject({
    mode: "recompose",
    input_artifact_ids: [""],
  });
});

it("synchronizes a duplicated main instruction but preserves intentional optional style guidance", () => {
  expect(
    syncImageBrief(initial, brief, "A new instruction")?.request,
  ).toMatchObject({ edit_prompt: "A new instruction" });
  const styled = {
    ...initial,
    request: {
      ...initial.request,
      edit_prompt: "Blue jacket and soft daylight",
    },
  } as AgentMediaScope;
  expect(syncImageBrief(styled, brief, "A new instruction")).toEqual(styled);
  if (styled.kind === "image")
    expect(agentMediaIssue({ ...styled, vary_scenes: true })).toContain(
      "reviewed reference",
    );
});

it("shows the planned shot and actual image prompt beside an agent result", () => {
  const runs = [
    {
      id: "prepare",
      task_id: "task",
      executor_type: "agent_media",
      status: "succeeded",
      parameters: {
        image_scene: {
          preserve: ["Oak finish"],
          changes: {
            setting: "A quiet hallway",
            composition: "Three-quarter view",
          },
        },
      },
    },
    {
      id: "image",
      task_id: "task",
      executor_type: "photo_pipe",
      status: "succeeded",
      parameters: {
        prompt: "Create a wardrobe product image in a hallway",
        backend: "qwen",
        steps: 30,
        cfg: 6,
        width: 832,
        height: 1216,
      },
    },
  ] as unknown as Run[];
  render(
    <Frame>
      <AgentMediaResult runs={runs} />
    </Frame>,
  );
  expect(
    screen.getByRole("heading", { name: "This run's image plan" }),
  ).toBeTruthy();
  expect(screen.getByText("A quiet hallway")).toBeTruthy();
  fireEvent.click(screen.getByText("Generation settings"));
  expect(screen.getByText("30")).toBeTruthy();
  expect(screen.getByText("832 × 1216")).toBeTruthy();
  fireEvent.click(screen.getByText("Image prompt"));
  expect(
    screen.getByText("Create a wardrobe product image in a hallway"),
  ).toBeTruthy();
});
