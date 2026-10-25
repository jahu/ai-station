import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import ConversationComposer from "./ConversationComposer";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
});

it("records a microphone draft only after Stop and sends Polish to the local transcription Run", async () => {
  const trackStop = vi.fn();
  class Recorder {
    static isTypeSupported = () => true;
    state = "inactive";
    mimeType = "audio/webm;codecs=opus";
    ondataavailable?: (event: { data: Blob }) => void;
    onstop?: () => void;
    start() {
      this.state = "recording";
    }
    stop() {
      this.state = "inactive";
      this.ondataavailable?.({
        data: new Blob(["audio"], { type: this.mimeType }),
      });
      this.onstop?.();
    }
  }
  const getUserMedia = vi.fn(async () => ({
    getTracks: () => [{ stop: trackStop }],
  }));
  vi.stubGlobal("MediaRecorder", Recorder);
  vi.stubGlobal("navigator", { mediaDevices: { getUserMedia } });
  const state = mount();
  fireEvent.click(screen.getByRole("button", { name: "Dictation options" }));
  fireEvent.change(
    screen.getByRole("combobox", { name: "Dictation language" }),
    { target: { value: "pl" } },
  );
  const dictate = screen.getByRole("button", { name: "Dictate" });
  await waitFor(() =>
    expect((dictate as HTMLButtonElement).disabled).toBe(false),
  );
  expect(getUserMedia).not.toHaveBeenCalled();
  fireEvent.click(dictate);
  await screen.findByRole("button", { name: "Stop recording" });
  expect(state.writes).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "Stop recording" }));
  await waitFor(() => expect(state.writes).toHaveLength(2));
  expect(trackStop).toHaveBeenCalled();
  expect(state.writes[1].body?.language).toBe("pl");
  await state.completeQueue();
  await state.complete();
  expect(state.send).not.toHaveBeenCalled();
});

function mount({ available = true, loseAcknowledgement = false } = {}) {
  const writes: { path: string; body?: Record<string, unknown> }[] = [];
  let finish!: (value: unknown) => void;
  let status = "running";
  let calls = 0;
  const run = () => ({
    id: "dictation-run",
    status,
    parameters: { parent_artifact_ids: ["recording"] },
    metadata: {
      transcription: {
        text: "Sprawdź dzisiejszą pogodę.",
        artifacts: { txt: "transcript" },
      },
    },
  });
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const fetch = vi.fn(async (path: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      writes.push({
        path,
        body:
          !init.body || init.body instanceof FormData
            ? undefined
            : JSON.parse(String(init.body)),
      });
      if (path.endsWith("/uploads"))
        return { ok: true, json: async () => ({ id: "recording" }) };
      if (path.endsWith("/cancel")) {
        status = "canceled";
        return { ok: true, json: async () => run() };
      }
      if (path.endsWith("/runs")) {
        calls++;
        if (loseAcknowledgement && calls === 1)
          throw new TypeError("Lost acknowledgement");
        return new Promise((resolve) => {
          finish = (value) => resolve({ ok: true, json: async () => value });
        });
      }
    }
    return {
      ok: true,
      json: async () =>
        path.includes("/capabilities")
          ? { available, reason: "Whisper is not configured" }
          : run(),
    };
  });
  vi.stubGlobal("fetch", fetch);
  const send = vi.fn();
  function Composer() {
    const [draft, setDraft] = useState("Initial draft");
    return (
      <ConversationComposer
        id="message"
        value={draft}
        onChange={setDraft}
        onSend={send}
        canSend
        busy={false}
        placeholder="Ask"
        tools={<button type="button">Keep attachment</button>}
      />
    );
  }
  const view = render(
    <QueryClientProvider client={cache}>
      <MemoryRouter>
        <Composer />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return {
    ...view,
    cache,
    writes,
    send,
    completeQueue: async () => {
      await waitFor(() => expect(finish).toBeTypeOf("function"));
      await act(async () => finish(run()));
    },
    complete: async () => {
      status = "succeeded";
      await act(async () => {
        cache.setQueryData(["run", "dictation-run"], run());
      });
    },
  };
}
async function startFile() {
  fireEvent.click(screen.getByRole("button", { name: "Dictation options" }));
  const input = screen.getByLabelText("Dictation audio file");
  await waitFor(() => expect((input as HTMLInputElement).disabled).toBe(false));
  fireEvent.change(input, {
    target: {
      files: [new File(["wav-data"], "dictation.wav", { type: "audio/wav" })],
    },
  });
}

it("inserts local speech at the saved caret, preserves attachments and never sends", async () => {
  const state = mount();
  const draft = screen.getByRole("textbox", {
    name: "Message",
  }) as HTMLTextAreaElement;
  draft.setSelectionRange(7, 7);
  await startFile();
  fireEvent.keyDown(draft, { key: "Enter" });
  expect(state.send).not.toHaveBeenCalled();
  await state.completeQueue();
  await state.complete();
  await waitFor(() =>
    expect(draft.value).toBe("Initial Sprawdź dzisiejszą pogodę. draft"),
  );
  expect(screen.getByText("Keep attachment")).toBeTruthy();
  expect(
    screen.getByLabelText("Dictation recording").getAttribute("src"),
  ).toContain("recording");
  expect(state.writes.map((item) => item.path)).toEqual([
    "/api/audio/transcription/uploads",
    "/api/audio/transcription/runs",
  ]);
  expect(state.send).not.toHaveBeenCalled();
  fireEvent.keyDown(draft, { key: "Enter" });
  expect(state.send).toHaveBeenCalledOnce();
});

it("protects edits during transcription and lets the operator insert or replace explicitly", async () => {
  const state = mount();
  await startFile();
  await state.completeQueue();
  const draft = screen.getByRole("textbox", {
    name: "Message",
  }) as HTMLTextAreaElement;
  fireEvent.change(draft, { target: { value: "My edited draft" } });
  await state.complete();
  await screen.findByText(/Your draft changed/);
  expect(draft.value).toBe("My edited draft");
  draft.setSelectionRange(3, 3);
  fireEvent.click(screen.getByRole("button", { name: "Insert at cursor" }));
  await waitFor(() =>
    expect(draft.value).toBe("My Sprawdź dzisiejszą pogodę. edited draft"),
  );
  expect(state.send).not.toHaveBeenCalled();
});

it("cancels a Run acknowledged after Cancel and never adopts its transcript", async () => {
  const state = mount();
  await startFile();
  await waitFor(() => expect(state.writes).toHaveLength(2));
  fireEvent.click(screen.getByRole("button", { name: "Cancel dictation" }));
  await state.completeQueue();
  await waitFor(() =>
    expect(state.writes.some((item) => item.path.endsWith("/cancel"))).toBe(
      true,
    ),
  );
  await state.complete();
  expect(
    (screen.getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement)
      .value,
  ).toBe("Initial draft");
  expect(state.send).not.toHaveBeenCalled();
});

it("cancels a late queue acknowledgement after navigation", async () => {
  const state = mount();
  await startFile();
  await waitFor(() => expect(state.writes).toHaveLength(2));
  state.unmount();
  await state.completeQueue();
  await waitFor(() =>
    expect(state.writes.some((item) => item.path.endsWith("/cancel"))).toBe(
      true,
    ),
  );
  expect(state.send).not.toHaveBeenCalled();
});

it("retries a lost acknowledgement with the same identity and saved recording", async () => {
  const state = mount({ loseAcknowledgement: true });
  await startFile();
  await screen.findByText("Lost acknowledgement");
  const body = state.writes.at(-1)?.body;
  fireEvent.click(screen.getByRole("button", { name: "Retry dictation" }));
  await waitFor(() => expect(state.writes).toHaveLength(3));
  expect(state.writes.at(-1)?.body).toEqual(body);
  await state.completeQueue();
  await state.complete();
  expect(
    state.writes.filter((item) => item.path.endsWith("/uploads")),
  ).toHaveLength(1);
  expect(state.send).not.toHaveBeenCalled();
});

it("explains missing local runtime without asking for a microphone or enqueuing", async () => {
  const state = mount({ available: false });
  fireEvent.click(screen.getByRole("button", { name: "Dictation options" }));
  await screen.findByText("Whisper is not configured");
  expect(
    (screen.getByRole("button", { name: "Dictate" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  expect(state.writes).toHaveLength(0);
});

it("explains HTTPS on plain HTTP LAN while offering local file transcription", async () => {
  vi.stubGlobal("isSecureContext", false);
  const state = mount();
  await startFile();
  expect(screen.getByText(/On this HTTP connection/)).toBeTruthy();
  await state.completeQueue();
  await state.complete();
  expect(state.send).not.toHaveBeenCalled();
});
