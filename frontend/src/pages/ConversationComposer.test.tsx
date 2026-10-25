import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render as renderUI,
  screen,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";
import ConversationComposer from "./ConversationComposer";

afterEach(cleanup);
function render(ui: ReactNode) {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
  return renderUI(ui, { wrapper });
}

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

it("opens and focuses selected follow-up tools without changing or submitting the draft", () => {
  const send = vi.fn();
  const props = {
    id: "draft",
    value: "Keep my next question",
    onChange: vi.fn(),
    onSend: send,
    canSend: true,
    busy: false,
    placeholder: "Ask…",
    tools: <p>Selected sales.csv</p>,
  };
  const { rerender } = render(
    <ConversationComposer {...props} toolSelectionKey={0} />,
  );
  expect(screen.getByText("Selected sales.csv").closest("details")?.open).toBe(
    false,
  );
  rerender(<ConversationComposer {...props} toolSelectionKey={1} />);
  expect(screen.getByText("Selected sales.csv").closest("details")?.open).toBe(
    true,
  );
  const draft = screen.getByRole("textbox", {
    name: "Message",
  }) as HTMLTextAreaElement;
  expect(draft.value).toBe("Keep my next question");
  expect(document.activeElement).toBe(draft);
  expect(send).not.toHaveBeenCalled();
  fireEvent.keyDown(draft, { key: "Enter" });
  expect(send).toHaveBeenCalledOnce();
  expect(screen.getByText("Selected sales.csv").closest("details")?.open).toBe(
    false,
  );
  expect(draft.value).toBe("Keep my next question");
});
