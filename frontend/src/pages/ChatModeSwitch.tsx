export type ChatMode = "chat" | "work";

export default function ChatModeSwitch({
  value,
  onChange,
  disabled,
}: {
  value: ChatMode;
  onChange: (mode: ChatMode) => void;
  disabled?: boolean;
}) {
  return (
    <div
      className="chat-mode-switch"
      role="group"
      aria-label="Conversation mode"
    >
      {(["chat", "work"] as const).map((mode) => (
        <button
          key={mode}
          type="button"
          aria-pressed={value === mode}
          disabled={disabled}
          onClick={() => onChange(mode)}
          title={
            mode === "chat"
              ? "Conversation, search and media"
              : "Projects, coding and agents"
          }
        >
          {mode === "chat" ? "Chat" : "Work"}
        </button>
      ))}
    </div>
  );
}
