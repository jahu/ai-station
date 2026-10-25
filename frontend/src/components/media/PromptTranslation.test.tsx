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
import type { Run } from "../../api";
import PromptTranslation, {
  PromptTranslationControl,
  type TranslationOptions,
} from "./PromptTranslation";
import GenerationSettings from "../../pages/GenerationSettings";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const receipt = {
  status: "waiting_for_review",
  preparation_run_id: "prep",
  review_run_id: "review",
  original: { prompt: 'Czerwony rower, napis "Dzień dobry"' },
  effective: { prompt: 'A red bicycle, text "Dzień dobry"' },
  policy: { model: "local-translator", target_language: "en" },
};
function mount({
  review = true,
  settings = false,
  control = false,
  loseAcknowledgement = false,
  film = false,
  executor = "photo_pipe",
} = {}) {
  const writes: { path: string; body?: Record<string, unknown> }[] = [];
  let sourceStatus = review ? "queued" : "failed",
    attempts = 0;
  const source = () =>
    ({
      id: "media",
      status: sourceStatus,
      parameters: { prompt: receipt.original.prompt },
      metadata: {
        prompt_translation: {
          ...receipt,
          status: review ? "waiting_for_review" : "queued",
          review_run_id: review ? "review" : undefined,
        },
      },
      project_id: null,
      task_id: "task",
      parent_run_id: null,
      capability: "image.generate",
      executor_type: executor,
      execution_target: "host",
      created_at: "2026-10-25T12:00:00Z",
      started_at: null,
      finished_at: null,
      actual_gpu: null,
      requested_gpu: "auto",
      effective_permissions: [],
      summary: "",
      error_type: "",
      error_message: "",
      worker_id: null,
    }) satisfies Run;
  const local = {
    model_ref: "local",
    model_key: "local-translator",
    display_name: "Local translator",
    provider_key: "local-openai-compatible",
    provider_name: "Local",
    location: "local",
    runtime_kind: "local-server",
    availability: "available",
    modalities: ["text"],
  };
  const fetch = vi.fn(async (path: string, init?: RequestInit) => {
    if (init?.method && init.method !== "GET") {
      const body = init.body ? JSON.parse(String(init.body)) : undefined;
      writes.push({ path, body });
      if (path.endsWith("/cancel")) {
        sourceStatus = "canceled";
        return { ok: true, json: async () => source() };
      }
      if (path.endsWith("/retry")) {
        attempts++;
        if (loseAcknowledgement && attempts === 1)
          throw new TypeError("Lost acknowledgement");
        return {
          ok: true,
          json: async () => ({ ...source(), id: "retry", status: "queued" }),
        };
      }
      return { ok: true, json: async () => ({ ...body, revision: 1 }) };
    }
    const value = path.endsWith("/generation/preferences")
      ? { revision: 0, enabled: false, model: "", target_language: "en" }
      : path.includes("model-catalog")
        ? {
            models: [
              local,
              {
                ...local,
                model_ref: "cloud",
                provider_key: "cloud",
                location: "external",
                runtime_kind: "external",
                display_name: "Cloud translator",
              },
            ],
            providers: [
              {
                key: "local-openai-compatible",
                name: "Local",
                location: "local",
                enabled: true,
              },
              {
                key: "cloud",
                name: "Cloud",
                location: "external",
                enabled: true,
              },
            ],
          }
        : path.endsWith("/review")
          ? {
              id: "review",
              status: "waiting_for_approval",
              parameters: { effective: receipt.effective },
              approval: { payload: { effective_hash: "a".repeat(64) } },
            }
          : path.endsWith("/prep")
            ? {
                id: "prep",
                status: review ? "succeeded" : "failed",
                error_message: review ? "" : "Translator unavailable",
              }
            : source();
    return { ok: true, json: async () => value };
  });
  vi.stubGlobal("fetch", fetch);
  function Controls() {
    const [value, setValue] = useState<TranslationOptions>({
      mode: "inherit",
      review: false,
      protected_terms: [],
    });
    return (
      <>
        <PromptTranslationControl
          value={value}
          onChange={setValue}
          disabled={false}
        />
        <output aria-label="Translation options snapshot">
          {JSON.stringify(value)}
        </output>
      </>
    );
  }
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={cache}>
      <MemoryRouter initialEntries={["/images?run=media"]}>
        {settings ? (
          <GenerationSettings />
        ) : control ? (
          <Controls />
        ) : (
          <PromptTranslation
            run={source()}
            onRecover={
              film
                ? async (action) => {
                    writes.push({
                      path: "whole-film-recovery",
                      body: { translation: action },
                    });
                  }
                : undefined
            }
          />
        )}
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { writes, fetch };
}

it("delegates film recovery to the whole workflow without canceling or retrying a single segment", async () => {
  const state = mount({ film: true, executor: "wan_video" });
  fireEvent.click(await screen.findByRole("button", { name: "Use original" }));
  await waitFor(() =>
    expect(state.writes).toEqual([
      { path: "whole-film-recovery", body: { translation: "original" } },
    ]),
  );
});

it("uses the typed media retry endpoint for standalone failed music translation", async () => {
  const state = mount({ review: false, executor: "ace_step_music" });
  fireEvent.click(await screen.findByRole("button", { name: "Use original" }));
  await waitFor(() => expect(state.writes).toHaveLength(1));
  expect(state.writes[0].path).toBe("/api/generation/media/media/retry");
  expect(state.writes[0].body?.translation).toBe("original");
});

it("keeps inherited translation off, supports explicit overrides and retains multiline names", async () => {
  const state = mount({ control: true });
  await screen.findByRole("option", {
    name: "Station default · Keep original",
  });
  expect(state.writes).toHaveLength(0);
  fireEvent.change(screen.getByRole("combobox", { name: "Prompt language" }), {
    target: { value: "on" },
  });
  fireEvent.click(
    screen.getByText("Translation options", { selector: "summary" }),
  );
  fireEvent.click(
    screen.getByRole("checkbox", { name: /Review before generation/ }),
  );
  const names = screen.getByRole("textbox", {
    name: "Names or trigger words to preserve",
  }) as HTMLTextAreaElement;
  fireEvent.change(names, {
    target: { value: "Jan Kowalski\nbrand_trigger\n" },
  });
  expect(names.value.endsWith("\n")).toBe(true);
  expect(
    JSON.parse(
      screen.getByLabelText("Translation options snapshot").textContent!,
    ),
  ).toEqual({
    mode: "on",
    review: true,
    protected_terms: ["Jan Kowalski", "brand_trigger"],
  });
});

it("shows original and prepared prompts without claiming the image was dispatched", async () => {
  mount();
  await screen.findByRole("button", { name: "Use translated prompt" });
  expect(screen.getByText("Prompt prepared for model")).toBeTruthy();
  expect(screen.queryByText("SENT TO MODEL")).toBeNull();
  expect(screen.getByText(receipt.original.prompt)).toBeTruthy();
});

it("edits the prepared text and binds approval to the server candidate hash", async () => {
  const state = mount();
  const prompt = await screen.findByRole("textbox", {
    name: "Translated prompt",
  });
  fireEvent.change(prompt, { target: { value: "A red bicycle at sunset" } });
  fireEvent.click(
    screen.getByRole("button", { name: "Use translated prompt" }),
  );
  await waitFor(() => expect(state.writes).toHaveLength(1));
  expect(state.writes[0]).toEqual({
    path: "/api/generation/translations/review/review",
    body: {
      expected_hash: "a".repeat(64),
      effective: { prompt: "A red bicycle at sunset" },
    },
  });
  expect(state.writes.some((item) => item.path.includes("/images/runs"))).toBe(
    false,
  );
});

it("uses original only after canceling the parked image and preserves retry identity", async () => {
  const state = mount({ loseAcknowledgement: true });
  fireEvent.click(await screen.findByRole("button", { name: "Use original" }));
  await screen.findByText("Lost acknowledgement");
  fireEvent.click(screen.getByRole("button", { name: "Use original" }));
  await waitFor(() =>
    expect(
      state.writes.filter((item) => item.path.endsWith("/retry")),
    ).toHaveLength(2),
  );
  expect(
    state.writes.filter((item) => item.path.endsWith("/cancel")),
  ).toHaveLength(1);
  const retries = state.writes.filter((item) => item.path.endsWith("/retry"));
  expect(retries[0].body).toEqual(retries[1].body);
  expect(retries[0].body?.translation).toBe("original");
});

it("offers explicit recovery for failed translation instead of pretending success", async () => {
  const state = mount({ review: false });
  await screen.findByText(/Translation did not complete/);
  fireEvent.click(screen.getByRole("button", { name: "Retry translation" }));
  await waitFor(() => expect(state.writes).toHaveLength(1));
  expect(state.writes[0].body?.translation).toBe("retry");
});

it("saves a versioned local translator without browsing external models or launching workloads", async () => {
  const state = mount({ settings: true });
  const toggle = await screen.findByRole("switch", {
    name: /Translate media prompts/,
  });
  expect((toggle as HTMLInputElement).checked).toBe(false);
  fireEvent.click(toggle);
  expect(
    (
      screen.getByRole("button", {
        name: "Save generation settings",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Change model" }));
  const selected = await screen.findByRole("button", {
    name: /Local translator/,
  });
  expect(screen.queryByText("Cloud translator")).toBeNull();
  expect(screen.queryByRole("button", { name: /Browse Cloud/ })).toBeNull();
  fireEvent.click(selected);
  fireEvent.click(
    screen.getByRole("button", { name: "Save generation settings" }),
  );
  await screen.findByText("Generation settings saved.");
  expect(state.writes).toEqual([
    {
      path: "/api/generation/preferences",
      body: {
        revision: 0,
        enabled: true,
        model: "local-translator",
        target_language: "en",
      },
    },
  ]);
});
