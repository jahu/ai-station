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
    type: "image",
    mime_type: "image/png",
    original_filename: id + ".png",
    parent_artifact_ids: [],
    metadata: { width: 80, height: 40 },
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      if (path === "/api/images/uploads") {
        uploads++;
        if (failSecond && uploads === 2)
          return {
            ok: false,
            json: async () => ({ detail: "Second image could not be stored" }),
          };
        return { ok: true, json: async () => artifact("image-" + uploads) };
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
function images(count: number) {
  return Array.from({ length: count }, (_, index) => {
    const file = new File(
      [new Uint8Array([0, 255, 80, 78])],
      `photo-${index}.png`,
      { type: "image/png" },
    );
    Object.defineProperty(file, "arrayBuffer", {
      value: () => {
        throw new Error(
          "Image must use the stored image tool, not inline base64",
        );
      },
    });
    return file;
  });
}

it.each([
  { mode: "chat", action: "auto", count: 1 },
  { mode: "chat", action: "chat", count: 2 },
  { mode: "work", action: "auto", count: 2 },
])(
  "stores ordinary images with a saved $mode preference and $action and sends their ordered ids instead of inline pixels",
  async ({ mode, action, count }) => {
    const state = mount({ mode });
    const message = await screen.findByRole("textbox", { name: "Message" });
    expect(
      screen.queryByRole("group", { name: "Conversation mode" }),
    ).toBeNull();
    if (action !== "auto")
      fireEvent.change(screen.getByRole("combobox", { name: "Action" }), {
        target: { value: action },
      });
    fireEvent.change(message, {
      target: { value: "Jaki kolor ma ten prostokąt?" },
    });
    fireEvent.change(screen.getByLabelText("Attach files"), {
      target: { files: images(count) },
    });
    await screen.findByAltText(`Reference ${count}`);
    expect(state.writes).toHaveLength(0);
    expect((message as HTMLTextAreaElement).value).toBe(
      "Jaki kolor ma ten prostokąt?",
    );
    await waitFor(() =>
      expect(
        (
          screen.getByRole("button", {
            name: "Send message",
          }) as HTMLButtonElement
        ).disabled,
      ).toBe(false),
    );
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(state.accepted).toHaveBeenCalledWith("saved"));
    expect(state.uploads()).toBe(count);
    expect(state.writes).toHaveLength(1);
    expect(state.writes[0]).toMatchObject({
      action,
      image_artifact_ids: Array.from(
        { length: count },
        (_, i) => "image-" + (i + 1),
      ),
      attachments: [],
      content: "Jaki kolor ma ten prostokąt?",
      web_search: { enabled: false },
    });
    expect(JSON.stringify(state.writes[0])).not.toContain("base64");
  },
);

it("keeps the stored image and parent error visible when a later upload fails", async () => {
  const state = mount({ failSecond: true });
  const message = await screen.findByRole("textbox", { name: "Message" });
  fireEvent.change(message, { target: { value: "Keep my question" } });
  fireEvent.change(screen.getByLabelText("Attach files"), {
    target: { files: images(2) },
  });
  await screen.findByText("Second image could not be stored");
  await screen.findByAltText("Reference 1");
  expect(screen.queryByLabelText("Attach files")).toBeNull();
  expect(screen.queryByAltText("Reference 2")).toBeNull();
  expect((message as HTMLTextAreaElement).value).toBe("Keep my question");
  expect(state.writes).toHaveLength(0);
});
