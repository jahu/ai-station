import { ArrowUp, Paperclip } from "lucide-react";
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { Button } from "../components/ui/button";
import { useDictation } from "./useDictation";
import { ComposerAttachmentTarget } from "./composer-attachment-target";

export default function ConversationComposer({
  id,
  value,
  onChange,
  onSend,
  canSend,
  busy,
  sendKey = "enter",
  placeholder,
  autoFocus = false,
  tools,
  controls,
  sendButton,
  sendLabel,
  permissionNote,
  toolSelectionKey = 0,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  canSend: boolean;
  busy: boolean;
  sendKey?: "enter" | "ctrl-enter";
  placeholder: string;
  autoFocus?: boolean;
  tools: ReactNode;
  controls?: ReactNode;
  sendButton?: ReactNode;
  sendLabel?: string;
  permissionNote?: ReactNode;
  toolSelectionKey?: number;
}) {
  const textarea = useRef<HTMLTextAreaElement>(null);
  const toolPanel = useRef<HTMLDetailsElement>(null);
  const [attachmentTarget, setAttachmentTarget] =
    useState<HTMLFieldSetElement | null>(null);
  const dictation = useDictation({ value, onChange, textarea, disabled: busy });
  useLayoutEffect(() => {
    if (toolSelectionKey && toolPanel.current) {
      toolPanel.current.open = true;
      textarea.current?.focus();
    }
  }, [toolSelectionKey]);
  useLayoutEffect(() => {
    const field = textarea.current;
    if (!field) return;
    // Reset first so deleting text and sending also shrink the composer.
    field.style.height = "auto";
    field.style.height = `${field.scrollHeight}px`;
  }, [value]);
  const submit = () => {
    if (canSend && !busy && !dictation.busy) {
      if (toolPanel.current) toolPanel.current.open = false;
      onSend();
    }
  };
  return (
    <ComposerAttachmentTarget.Provider value={attachmentTarget}>
      <form
        className="new-chat-composer shared-chat-composer"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
        onKeyDown={(event) => {
          if (
            event.key === "Enter" &&
            (event.target as HTMLElement).matches("input:not([type='file'])")
          )
            event.preventDefault();
        }}
      >
        <fieldset
          ref={setAttachmentTarget}
          className="composer-selected-inputs"
          aria-label="Selected attachments"
          disabled={dictation.busy}
        />
        <label className="sr-only" htmlFor={id}>
          Message
        </label>
        <textarea
          ref={textarea}
          id={id}
          autoFocus={autoFocus}
          rows={1}
          maxLength={32000}
          value={value}
          placeholder={placeholder}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (
              event.key !== "Enter" ||
              event.nativeEvent.isComposing ||
              event.shiftKey ||
              event.altKey ||
              (sendKey === "ctrl-enter" && !event.ctrlKey && !event.metaKey)
            )
              return;
            event.preventDefault();
            submit();
          }}
        />
        {dictation.panel}
        {permissionNote && <p className="muted">{permissionNote}</p>}
        {tools && (
          <details ref={toolPanel} className="new-chat-tools">
            <summary>
              <Paperclip size={16} aria-hidden="true" />
              <span>Attach files &amp; choose tools</span>
            </summary>
            <fieldset className="composer-tools-lock" disabled={dictation.busy}>
              {tools}
            </fieldset>
          </details>
        )}
        <div className="new-chat-footer">
          {controls}
          {dictation.action}
          {sendButton ?? (
            <Button
              type="submit"
              aria-label={sendLabel}
              title={
                sendKey === "ctrl-enter"
                  ? "Ctrl / Cmd + Enter to send"
                  : "Enter to send · Shift + Enter for a new line"
              }
              disabled={!canSend || busy || dictation.busy}
            >
              <ArrowUp size={18} /> Send
            </Button>
          )}
        </div>
      </form>
    </ComposerAttachmentTarget.Provider>
  );
}
