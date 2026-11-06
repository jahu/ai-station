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
import AgentImageModel from "./AgentImageModel";
import type { ImageMediaRequest } from "./agent-media";
import type { ImageModelCatalog } from "./image-models";

const krea = "11111111-1111-4111-8111-111111111111";
const installedQwen = "22222222-2222-4222-8222-222222222222";
const catalog: ImageModelCatalog = {
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
    {
      id: "juggernaut",
      definition_id: null,
      name: "Juggernaut XL",
      backend: "juggernaut",
      available: true,
      modes: ["t2i"],
      maximum_references: 0,
    },
    {
      id: krea,
      definition_id: krea,
      name: "Installed Krea",
      backend: "krea2",
      available: true,
      modes: ["t2i", "img2img", "recompose"],
      maximum_references: 2,
      presets: { recompose: { steps: 8, cfg: 1 } },
    },
    {
      id: installedQwen,
      definition_id: installedQwen,
      name: "Installed Qwen",
      backend: "qwen",
      available: true,
      modes: ["img2img", "recompose"],
      maximum_references: 8,
    },
    {
      id: "missing",
      definition_id: "missing",
      name: "Missing checkpoint",
      backend: "qwen",
      available: false,
      modes: ["img2img", "recompose"],
      maximum_references: 8,
    },
  ],
  defaults: {
    revision: 1,
    choices: {
      t2i: "qwen",
      img2img: "qwen",
      recompose: krea,
      upscale: "realesrgan",
    },
  },
};
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function Editor({
  initial,
  disabled = false,
}: {
  initial: ImageMediaRequest;
  disabled?: boolean;
}) {
  const [request, setRequest] = useState(initial);
  return (
    <>
      <AgentImageModel
        request={request}
        disabled={disabled}
        onChange={setRequest}
      />
      <output aria-label="Saved image">{JSON.stringify(request)}</output>
    </>
  );
}
function show(initial: ImageMediaRequest, disabled = false) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, json: async () => catalog })),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <Editor initial={initial} disabled={disabled} />
    </QueryClientProvider>,
  );
}
function saved(): ImageMediaRequest {
  return JSON.parse(screen.getByLabelText("Saved image").textContent!);
}

it.each(["img2img", "recompose"] as const)(
  "changes the model of an existing %s agent without losing references or instructions",
  async (mode) => {
    const original: ImageMediaRequest = {
      mode,
      backend: "qwen",
      prompt: "A different room",
      edit_prompt: "Change the lighting",
      input_artifact_ids: ["source"],
      steps: 30,
      cfg: 6,
    };
    show(original);
    const select = screen.getByLabelText(
      "Agent image model",
    ) as HTMLSelectElement;
    await screen.findByRole("option", { name: "Installed Krea" });
    expect(screen.queryByRole("option", { name: "Juggernaut XL" })).toBeNull();
    expect(saved()).toEqual(original);
    fireEvent.change(select, { target: { value: krea } });
    expect(saved()).toMatchObject({
      mode,
      backend: "krea2",
      model_id: krea,
      input_artifact_ids: ["source"],
      prompt: original.prompt,
      edit_prompt: original.edit_prompt,
      steps: 8,
      cfg: 1,
      reference_layout: mode === "recompose" ? "beside" : "aligned",
    });
    fireEvent.change(select, { target: { value: installedQwen } });
    expect(saved()).toMatchObject({
      backend: "qwen",
      model_id: installedQwen,
      seed: null,
      negative: null,
      input_artifact_ids: ["source"],
      steps: 30,
    });
    expect(saved()).not.toHaveProperty("reference_layout");
    expect(saved()).not.toHaveProperty("reference_strength");
    expect(
      vi
        .mocked(fetch)
        .mock.calls.every(([, init]) => !init?.method || init.method === "GET"),
    ).toBe(true);
  },
);

it("keeps an unavailable saved model and all settings until an explicit replacement", async () => {
  const original: ImageMediaRequest = {
    mode: "recompose",
    backend: "krea2",
    model_id: "deleted-model",
    input_artifact_ids: ["source"],
    cfg: 2,
    reference_layout: "aligned",
  };
  show(original);
  await screen.findByRole("option", { name: "Installed Krea" });
  expect(
    (screen.getByLabelText("Agent image model") as HTMLSelectElement).value,
  ).toBe("deleted-model");
  expect(saved()).toEqual(original);
});

it("disables unavailable and reference-incompatible models without dropping source images", async () => {
  show({
    mode: "recompose",
    backend: "qwen",
    input_artifact_ids: ["one", "two", "three"],
  });
  const option = (await screen.findByRole("option", {
    name: /Installed Krea/,
  })) as HTMLOptionElement;
  expect(option.disabled).toBe(true);
  expect(
    (
      screen.getByRole("option", {
        name: /Missing checkpoint/,
      }) as HTMLOptionElement
    ).disabled,
  ).toBe(true);
  fireEvent.change(screen.getByLabelText("Agent image model"), {
    target: { value: krea },
  });
  expect(saved().backend).toBe("qwen");
  expect(saved().input_artifact_ids).toHaveLength(3);
});

it("shows a load error, keeps the saved configuration and supports retry", async () => {
  const initial: ImageMediaRequest = {
    mode: "img2img",
    backend: "qwen",
    edit_prompt: "New lighting",
    input_artifact_ids: ["source"],
  };
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 503,
        text: async () => "Unavailable",
      })
      .mockResolvedValue({ ok: true, json: async () => catalog }),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <Editor initial={initial} />
    </QueryClientProvider>,
  );
  await screen.findByRole("alert");
  expect(saved()).toEqual(initial);
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await screen.findByRole("option", { name: "Installed Krea" });
  await waitFor(() =>
    expect(
      (screen.getByLabelText("Agent image model") as HTMLSelectElement)
        .disabled,
    ).toBe(false),
  );
});
