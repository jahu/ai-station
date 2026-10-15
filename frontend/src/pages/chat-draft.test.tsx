import { afterEach, expect, it, vi } from "vitest";
import {
  act,
  renderHook,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { clearChatDraft, useChatDraft } from "./chat-draft";

function Composer({ scope }: { scope: string }) {
  const draft = useChatDraft(scope);
  return (
    <>
      <textarea
        aria-label="Draft"
        value={draft.value}
        onChange={(event) => draft.update(event.target.value)}
      />
      {draft.restored && <p>Text restored</p>}
      <button onClick={() => draft.update("")}>Accepted</button>
    </>
  );
}
afterEach(() => {
  cleanup();
  sessionStorage.clear();
  vi.restoreAllMocks();
});
it("restores each conversation separately after navigation and clears accepted text", () => {
  const first = render(<Composer scope="one" />);
  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "My unfinished prompt" },
  });
  first.unmount();
  const second = render(<Composer scope="two" />);
  expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("");
  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "Another prompt" },
  });
  second.unmount();
  render(<Composer scope="one" />);
  expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe(
    "My unfinished prompt",
  );
  expect(screen.getByText("Text restored")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Accepted" }));
  cleanup();
  render(<Composer scope="one" />);
  expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("");
});
it("explicit New chat clears only the entry draft", () => {
  sessionStorage.setItem("ai-station:chat-draft:new", "Old entry");
  sessionStorage.setItem("ai-station:chat-draft:one", "Saved conversation");
  clearChatDraft("new");
  expect(sessionStorage.getItem("ai-station:chat-draft:new")).toBeNull();
  expect(sessionStorage.getItem("ai-station:chat-draft:one")).toBe(
    "Saved conversation",
  );
});
it("storage failures preserve typing and accepted-message clearing", () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("Blocked");
  });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("Quota");
  });
  vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
    throw new Error("Blocked");
  });
  render(<Composer scope="one" />);
  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "Still editable" },
  });
  expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe(
    "Still editable",
  );
  fireEvent.click(screen.getByRole("button"));
  expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("");
});

it("keeps the same receipt identity for an unchanged retry after reload, but not a new intent", async () => {
  const randomUUID = crypto.randomUUID.bind(crypto);
  const { chatRequestId, clearChatRequest } = await import("./chat-draft");
  vi.stubGlobal("crypto", {
    randomUUID,
    subtle: {
      digest: vi.fn(async (_algorithm, data: Uint8Array) => data.buffer),
    },
  });
  try {
    const first = await chatRequestId("new", '{"content":"Build this"}');
    expect(await chatRequestId("new", '{"content":"Build this"}')).toBe(first);
    expect(await chatRequestId("other", '{"content":"Build this"}')).not.toBe(
      first,
    );
    expect(await chatRequestId("new", '{"content":"Another task"}')).not.toBe(
      first,
    );
    clearChatRequest("new");
    expect(await chatRequestId("new", '{"content":"Build this"}')).not.toBe(
      first,
    );
    expect(sessionStorage.getItem("ai-station:chat-request:new")).not.toContain(
      "Build this",
    );
  } finally {
    vi.unstubAllGlobals();
  }
});

it("keeps a newer draft when an earlier Send is accepted", () => {
  const { result, unmount } = renderHook(() => useChatDraft("one"));
  act(() => result.current.update("First prompt"));
  const submitted = result.current.value;
  act(() => result.current.update("My next prompt"));
  act(() => result.current.accept(submitted));
  expect(result.current.value).toBe("My next prompt");
  unmount();
  const restored = renderHook(() => useChatDraft("one"));
  expect(restored.result.current.value).toBe("My next prompt");
});

it("retains retry receipts over LAN HTTP without subtle or randomUUID", async () => {
  const source = crypto;
  vi.stubGlobal("crypto", {
    getRandomValues: source.getRandomValues.bind(source),
  });
  try {
    const { chatRequestId, clearChatRequest } = await import("./chat-draft");
    const first = await chatRequestId("lan", "abc");
    expect(first).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
    expect(
      JSON.parse(sessionStorage.getItem("ai-station:chat-request:lan")!).hash,
    ).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    vi.resetModules();
    const reloaded = await import("./chat-draft");
    expect(await reloaded.chatRequestId("lan", "abc")).toBe(first);
    expect(await reloaded.chatRequestId("lan", "different")).not.toBe(first);
    clearChatRequest("lan");
    expect(await chatRequestId("lan", "abc")).not.toBe(first);
  } finally {
    vi.unstubAllGlobals();
  }
});
