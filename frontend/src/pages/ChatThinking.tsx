import { Brain } from "lucide-react";

export default function ChatThinking({
  value,
  busy,
  blocked,
  onChange,
}: {
  value: boolean;
  busy: boolean;
  blocked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-label="Thinking"
      aria-checked={value}
      className="web-search-toggle chat-thinking-control"
      disabled={busy || blocked}
      onClick={() => onChange(!value)}
      title={
        blocked
          ? "Increase the response limit to at least 512 tokens in conversation settings"
          : "Verified local thinking; uses part of the response token budget"
      }
    >
      <Brain size={16} />
      <span>Thinking</span>
      <span className="chip">{value ? "ON" : "OFF"}</span>
    </button>
  );
}
