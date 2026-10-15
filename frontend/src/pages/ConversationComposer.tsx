import { ArrowUp, Paperclip } from "lucide-react";
import { useLayoutEffect, useRef, type ReactNode } from "react";
import { Button } from "../components/ui/button";

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
}) {
  const textarea = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const field = textarea.current;
    if (!field) return;
    // Reset first so deleting text and sending also shrink the composer.
    field.style.height = "auto";
    field.style.height = `${field.scrollHeight}px`;
  }, [value]);
  const submit = () => {
    if (canSend && !busy) onSend();
  };
  return (
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
      {permissionNote && <p className="muted">{permissionNote}</p>}
      {tools && (
        <details className="new-chat-tools">
          <summary>
            <Paperclip size={16} aria-hidden="true" />
            <span>Attach files &amp; choose tools</span>
          </summary>
          {tools}
        </details>
      )}
      <div className="new-chat-footer">
        {controls}
        {sendButton ?? (
          <Button
            type="submit"
            aria-label={sendLabel}
            title={
              sendKey === "ctrl-enter"
                ? "Ctrl / Cmd + Enter to send"
                : "Enter to send · Shift + Enter for a new line"
            }
            disabled={!canSend || busy}
          >
            <ArrowUp size={18} /> Send
          </Button>
        )}
      </div>
    </form>
  );
}
