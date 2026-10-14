import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import ConversationComposer from "./ConversationComposer";

afterEach(cleanup);

it.each(["enter", "ctrl-enter"] as const)(
  "honors %s, multiline and composition without submitting tool edits",
  (sendKey) => {
    const send = vi.fn();
    render(
      <ConversationComposer
        id="draft"
        value="A task"
        onChange={() => {}}
        onSend={send}
        canSend
        busy={false}
        sendKey={sendKey}
        placeholder="Ask…"
        tools={<input aria-label="Tool setting" />}
      />,
    );
    const draft = screen.getByRole("textbox", { name: "Message" });
    fireEvent.keyDown(draft, { key: "Enter", shiftKey: true });
    fireEvent.keyDown(draft, { key: "Enter", isComposing: true });
    fireEvent.keyDown(draft, { key: "Enter", altKey: true });
    fireEvent.keyDown(
      screen.getByRole("textbox", { name: "Tool setting", hidden: true }),
      { key: "Enter" },
    );
    expect(send).not.toHaveBeenCalled();
    fireEvent.keyDown(draft, { key: "Enter" });
    expect(send).toHaveBeenCalledTimes(sendKey === "enter" ? 1 : 0);
    fireEvent.keyDown(draft, { key: "Enter", metaKey: true });
    expect(send).toHaveBeenCalledTimes(sendKey === "enter" ? 2 : 1);
  },
);

it("keeps Stop independent of Send while an active turn allows typing", () => {
  const send = vi.fn(),
    stop = vi.fn(),
    edit = vi.fn();
  render(
    <ConversationComposer
      id="draft"
      value="Next task"
      onChange={edit}
      onSend={send}
      canSend
      busy
      placeholder="Ask…"
      tools={null}
      sendButton={
        <button type="button" onClick={stop}>
          Stop
        </button>
      }
    />,
  );
  const draft = screen.getByRole("textbox", { name: "Message" });
  fireEvent.change(draft, { target: { value: "Keep this next draft" } });
  expect(edit).toHaveBeenCalledWith("Keep this next draft");
  fireEvent.keyDown(draft, { key: "Enter" });
  fireEvent.click(screen.getByRole("button", { name: "Stop" }));
  expect(stop).toHaveBeenCalledOnce();
  expect(send).not.toHaveBeenCalled();
});
