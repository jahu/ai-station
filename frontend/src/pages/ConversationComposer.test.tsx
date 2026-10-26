import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render as renderUI,
  screen,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { useState, type ReactNode } from "react";
import ConversationComposer from "./ConversationComposer";
import TextAttachments, { type TextAttachment } from "./TextAttachments";
import ComposerAttachments from "./ComposerAttachments";

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

function AttachmentComposer({ onSend }: { onSend: () => void }) {
  const [files, setFiles] = useState<TextAttachment[]>([]);
  return (
    <ConversationComposer
      id="attachment-draft"
      value="Keep this question"
      onChange={() => {}}
      onSend={onSend}
      canSend
      busy={false}
      placeholder="Ask…"
      tools={
        <TextAttachments
          attachments={files}
          onChange={setFiles}
          busy={false}
          onReading={() => {}}
        />
      }
    />
  );
}

function attachment(name: string, text: string) {
  const file = new File([text], name, { type: "text/plain" });
  Object.defineProperty(file, "arrayBuffer", {
    value: async () => new TextEncoder().encode(text).buffer,
  });
  return file;
}

it("retains removable attachments beside the draft after tools are collapsed", async () => {
  const send = vi.fn();
  render(<AttachmentComposer onSend={send} />);
  fireEvent.click(screen.getByText("Attach files & choose tools"));
  fireEvent.change(screen.getByLabelText("Attach files"), {
    target: { files: [attachment("notes.txt", "A private note")] },
  });
  const selected = await screen.findByLabelText("Attachment notes.txt");
  fireEvent.click(screen.getByText("Attach files & choose tools"));
  expect(selected.closest("details")).toBeNull();
  expect(selected.closest("fieldset")?.getAttribute("aria-label")).toBe(
    "Selected attachments",
  );
  expect(screen.getByRole("textbox", { name: "Message" })).toHaveProperty(
    "value",
    "Keep this question",
  );
  fireEvent.click(screen.getByRole("button", { name: "Remove notes.txt" }));
  expect(screen.queryByLabelText("Attachment notes.txt")).toBeNull();
  expect(send).not.toHaveBeenCalled();
});

it("keeps attachment errors visible when tools are closed without submitting", async () => {
  const send = vi.fn();
  render(<AttachmentComposer onSend={send} />);
  fireEvent.click(screen.getByText("Attach files & choose tools"));
  fireEvent.change(screen.getByLabelText("Attach files"), {
    target: { files: [attachment("large.txt", "x".repeat(16001))] },
  });
  const error = await screen.findByText("large.txt exceeds 16 KB.");
  fireEvent.click(screen.getByText("Attach files & choose tools"));
  expect(error.closest("details")).toBeNull();
  expect(send).not.toHaveBeenCalled();
});

it("isolates selected-input surfaces between two composers", () => {
  const props = {
    value: "",
    onChange: vi.fn(),
    onSend: vi.fn(),
    canSend: false,
    busy: false,
    placeholder: "Ask…",
  };
  render(
    <>
      <ConversationComposer
        {...props}
        id="one"
        tools={
          <ComposerAttachments>
            <span>First selection</span>
          </ComposerAttachments>
        }
      />
      <ConversationComposer
        {...props}
        id="two"
        tools={
          <ComposerAttachments>
            <span>Second selection</span>
          </ComposerAttachments>
        }
      />
    </>,
  );
  const first = screen.getByText("First selection"),
    second = screen.getByText("Second selection");
  expect(first.closest("form")).not.toBe(second.closest("form"));
  expect(first.closest("details")).toBeNull();
  expect(second.closest("details")).toBeNull();
});
