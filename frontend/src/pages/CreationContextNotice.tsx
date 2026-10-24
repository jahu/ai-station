export type CreationContext = {
  messages: {
    role: "user" | "assistant";
    content: string;
    truncated: boolean;
  }[];
  older_messages_omitted: boolean;
};

export default function CreationContextNotice({
  value,
  active = true,
}: {
  value?: CreationContext;
  active?: boolean;
}) {
  if (!value?.messages.length) return null;
  const limited =
    value.older_messages_omitted ||
    value.messages.some((item) => item.truncated);
  return (
    <details
      className="message-thinking"
      aria-label="Conversation context used for file creation"
    >
      <summary tabIndex={active ? 0 : -1}>
        Using {value.messages.length} earlier{" "}
        {value.messages.length === 1 ? "message" : "messages"}
        {limited ? " · Limited context" : ""}
      </summary>
      <p className="muted">
        This text was included to create your files. Attachments and website
        contents are not included.
        {limited &&
          " Some earlier text is omitted. Supply any missing exact values in your next message or attach a data file for analysis."}
      </p>
      {value.messages.map((item, index) => (
        <div key={index}>
          <strong>{item.role === "user" ? "You" : "AI Station"}</strong>
          <p className="whitespace-pre-wrap break-words">{item.content}</p>
          {item.truncated && <small className="muted">Excerpt only</small>}
        </div>
      ))}
    </details>
  );
}
