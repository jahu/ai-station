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
import AgentAvatarSetup from "./AgentAvatarSetup";
import AvatarMemoryProfile from "../components/media/AvatarMemoryProfile";
import Avatars from "./Avatars";

const avatar = {
  kind: "avatar" as const,
  description_source: "fixed" as const,
  request: {
    image_artifact_id: "portrait",
    audio_artifact_id: "speech",
    speech_text: null,
    prompt: "A person speaking",
    size: 384 as const,
    steps: 8,
    seed: 9381,
    gpu: "auto",
  },
};
const capabilities = {
  available: true,
  recommended_memory_profile: "bounded_11g",
  memory_profiles: [{ id: "bounded_11g", available: true }],
};
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function mount(children: React.ReactNode, path = "/avatars") {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={[path]}>{children}</MemoryRouter>
    </QueryClientProvider>,
  );
}
function fixture(whole = false) {
  const writes: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") writes.push(JSON.parse(String(init.body)));
      const request = writes.at(-1);
      return {
        ok: true,
        json: async () =>
          url.endsWith("/whole-capabilities")
            ? {
                backend: "sonic",
                available: whole,
                readiness: whole ? "ready" : "disabled",
              }
            : url.endsWith("/capabilities")
              ? capabilities
              : url.endsWith("/hardware")
                ? { gpus: [] }
                : url.includes("/media/jobs")
                  ? {
                      task_id: "avatar-job",
                      revision: 1,
                      kind: "avatar",
                      status: "queued",
                      active_run_ids: [],
                      total_segments: 2,
                      completed_segments: 0,
                      request,
                    }
                  : url.endsWith("portrait")
                    ? {
                        id: "portrait",
                        type: "image",
                        mime_type: "image/png",
                        original_filename: "Portrait.png",
                      }
                    : url.endsWith("speech")
                      ? {
                          id: "speech",
                          type: "audio",
                          mime_type: "audio/wav",
                          original_filename: "Speech.wav",
                        }
                      : [],
      };
    }),
  );
  return writes;
}

it("offers stable detail explicitly without changing a saved agent until Apply", async () => {
  const writes = fixture(true);
  const apply = vi.fn();
  mount(
    <AgentAvatarSetup
      value={{ ...avatar, description_source: "goal" }}
      maximumRuntime={600}
      onApply={apply}
    />,
  );
  const button = await screen.findByRole("button", {
    name: "Use suggested setup",
  });
  await screen.findByText(/Stable detail animates the whole recording/);
  expect(apply).not.toHaveBeenCalled();
  fireEvent.click(button);
  const patch = apply.mock.calls[0][0];
  expect(patch.maximum_runtime).toBe(14400);
  expect(patch.media.description_source).toBe("fixed");
  expect(patch.media.request).toEqual({
    image_artifact_id: "portrait",
    audio_artifact_id: "speech",
    speech_text: null,
    prompt: avatar.request.prompt,
    seed: 9381,
    gpu: "auto",
    generation_profile: "sonic_whole_768_v1",
  });
  expect(writes).toHaveLength(0);
});

it("stages a bounded setup only after action and preserves all reviewed sources and custom limits", async () => {
  const writes = fixture();
  const apply = vi.fn();
  mount(
    <AgentAvatarSetup value={avatar} maximumRuntime={9107} onApply={apply} />,
  );
  const button = await screen.findByRole("button", {
    name: "Use suggested setup",
  });
  expect(apply).not.toHaveBeenCalled();
  fireEvent.click(button);
  expect(apply).toHaveBeenCalledWith({
    maximum_runtime: 9107,
    media: {
      ...avatar,
      request: { ...avatar.request, memory_profile: "bounded_11g" },
    },
  });
  expect(writes).toHaveLength(0);
});

it.each([{ size: 512 as const }, { steps: 4 }])(
  "preserves an incompatible format while offering time only",
  async (change) => {
    fixture();
    const scope = { ...avatar, request: { ...avatar.request, ...change } };
    const apply = vi.fn();
    mount(
      <AgentAvatarSetup value={scope} maximumRuntime={600} onApply={apply} />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Use suggested setup" }),
    );
    expect(apply).toHaveBeenCalledWith({ maximum_runtime: 7200, media: scope });
  },
);

it("keeps active definitions read-only", async () => {
  fixture();
  const apply = vi.fn();
  mount(
    <AgentAvatarSetup
      value={avatar}
      maximumRuntime={600}
      disabled
      onApply={apply}
    />,
  );
  const button = await screen.findByRole("button", {
    name: "Use suggested setup",
  });
  fireEvent.click(button);
  expect((button as HTMLButtonElement).disabled).toBe(true);
  expect(apply).not.toHaveBeenCalled();
});

it("retains an unavailable saved profile and offers recovery to Standard", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, json: async () => ({ available: false }) })),
  );
  const change = vi.fn();
  mount(<AvatarMemoryProfile value="bounded_11g" onChange={change} />);
  await screen.findByText(/This saved profile is unavailable/);
  const select = screen.getByLabelText(
    "Avatar generation profile",
  ) as HTMLSelectElement;
  expect(select.value).toBe("bounded_11g");
  fireEvent.change(select, { target: { value: "default" } });
  expect(change).toHaveBeenCalledWith("default");
});

it.each([false, true])(
  "freezes the selected fresh-workspace profile on Send, with explicit Standard override=%s",
  async (standard) => {
    const writes = fixture();
    mount(<Avatars />, "/avatars?image=portrait&audio=speech");
    const select = (await screen.findByLabelText(
      "Avatar generation profile",
    )) as HTMLSelectElement;
    await waitFor(() => expect(select.value).toBe("bounded_11g"));
    if (standard) fireEvent.change(select, { target: { value: "default" } });
    fireEvent.click(
      screen.getByRole("button", { name: "Generate avatar video" }),
    );
    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0]).toMatchObject({
      image_artifact_id: "portrait",
      audio_artifact_id: "speech",
      size: 384,
      steps: 8,
      seed: 43,
    });
    if (standard) expect(writes[0]).not.toHaveProperty("memory_profile");
    else expect(writes[0].memory_profile).toBe("bounded_11g");
  },
);
