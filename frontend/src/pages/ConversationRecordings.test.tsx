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
import NewChat from "./NewChat";
import type { ChatProviderInfo } from "./ChatProviders";

const provider = {
  key: "local-openai-compatible",
  enabled: true,
  builtin: true,
  location: "local",
  default_model: "plain",
  models: ["plain"],
  secret_source: "none",
  secret_present: false,
} as ChatProviderInfo;
afterEach(() => {
  cleanup();
  sessionStorage.clear();
  vi.unstubAllGlobals();
});

function mount({ mode = "chat", failSecond = false } = {}) {
  let uploads = 0;
  const accepted = vi.fn();
  const writes: Record<string, unknown>[] = [];
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const artifact = (id: string) => ({
    id,
    type: "audio",
    mime_type: "audio/mpeg",
    original_filename: id + ".mp3",
    parent_artifact_ids: [],
    metadata: { input_format: "mp3", operation: "transcription.input" },
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      if (path === "/api/audio/transcription/uploads") {
        uploads++;
        if (failSecond)
          return {
            ok: false,
            json: async () => ({ detail: "Recording could not be stored" }),
          };
        return { ok: true, json: async () => artifact("audio-" + uploads) };
      }
      if (init?.method === "POST") {
        writes.push(JSON.parse(String(init.body)));
        return { ok: true, json: async () => ({ conversation_id: "saved" }) };
      }
      const data = path.endsWith("/preferences")
        ? { mode, provider: provider.key, model: "plain", version: 1 }
        : path.endsWith("/llama")
          ? { models: [], instances: [] }
          : path.includes("/artifacts/")
            ? artifact(path.split("/").at(-1)!)
            : [];
      return { ok: true, json: async () => data };
    }),
  );
  render(
    <QueryClientProvider client={cache}>
      <MemoryRouter>
        <NewChat
          providers={[provider]}
          provider={provider}
          onProviderChange={() => {}}
          onAccepted={accepted}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { accepted, writes, uploads: () => uploads };
}
function recording(name = "meeting.mp3") {
  const file = new File([new Uint8Array([73, 68, 51, 0, 255])], name, {
    type: "audio/mpeg",
  });
  Object.defineProperty(file, "arrayBuffer", {
    value: () => {
      throw new Error("Audio must be uploaded, never decoded as text");
    },
  });
  return file;
}

it.each(["chat", "work"])(
  "attaches a stored recording in %s without losing the prompt",
  async (mode) => {
    const state = mount({ mode });
    const message = await screen.findByRole("textbox", { name: "Message" });
    if (mode === "work")
      fireEvent.click(screen.getByRole("button", { name: "Work" }));
    fireEvent.change(message, { target: { value: "Podsumuj to nagranie" } });
    fireEvent.change(screen.getByLabelText("Attach files"), {
      target: { files: [recording()] },
    });
    await screen.findByLabelText("Recording preview");
    expect(screen.getByText(/audio-1.mp3/)).toBeTruthy();
    expect(state.writes).toHaveLength(0);
    expect((message as HTMLTextAreaElement).value).toBe("Podsumuj to nagranie");
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(state.accepted).toHaveBeenCalledWith("saved"));
    expect(state.uploads()).toBe(1);
    expect(state.writes[0]).toMatchObject({
      action: "auto",
      audio_artifact_id: "audio-1",
      image_artifact_ids: [],
      attachments: [],
      content: "Podsumuj to nagranie",
      web_search: { enabled: false },
    });
  },
);

it("removes a recording without losing the draft and allows another file", async () => {
  const state = mount();
  const message = await screen.findByRole("textbox", { name: "Message" });
  fireEvent.change(message, { target: { value: "Keep my question" } });
  fireEvent.change(screen.getByLabelText("Attach files"), {
    target: { files: [recording()] },
  });
  await screen.findByLabelText("Recording preview");
  fireEvent.click(screen.getByRole("button", { name: "Remove recording" }));
  expect(screen.queryByLabelText("Recording preview")).toBeNull();
  expect(screen.getByLabelText("Attach files")).toBeTruthy();
  expect((message as HTMLTextAreaElement).value).toBe("Keep my question");
  expect(state.writes).toHaveLength(0);
});

it("rejects mixed and multiple recordings before upload", async () => {
  const state = mount();
  await screen.findByRole("textbox", { name: "Message" });
  for (const files of [
    [recording(), recording("other.mp3")],
    [recording(), new File(["notes"], "notes.txt", { type: "text/plain" })],
  ]) {
    fireEvent.change(screen.getByLabelText("Attach files"), {
      target: { files },
    });
    await screen.findByText(/Choose one recording separately/);
  }
  expect(state.uploads()).toBe(0);
  expect(state.writes).toHaveLength(0);
});

it("keeps upload failure and the current question visible", async () => {
  const state = mount({ failSecond: true });
  const message = await screen.findByRole("textbox", { name: "Message" });
  fireEvent.change(message, { target: { value: "Keep my question" } });
  fireEvent.change(screen.getByLabelText("Attach files"), {
    target: { files: [recording()] },
  });
  await screen.findByText("Recording could not be stored");
  expect(screen.queryByLabelText("Recording preview")).toBeNull();
  expect((message as HTMLTextAreaElement).value).toBe("Keep my question");
  expect(state.writes).toHaveLength(0);
});
