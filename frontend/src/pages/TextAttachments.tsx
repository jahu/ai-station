import { useState } from "react";
import { ErrorNotice } from "../components/common";

export type TextAttachment = { name: string; content: string };

export default function TextAttachments({
  attachments,
  onChange,
  busy,
  onReading,
}: {
  attachments: TextAttachment[];
  onChange: (items: TextAttachment[]) => void;
  busy: boolean;
  onReading: (reading: boolean) => void;
}) {
  const [error, setError] = useState<Error | null>(null);
  const [reading, setReading] = useState(false);
  return (
    <div>
      <label>
        Attach text files
        <input
          type="file"
          multiple
          disabled={busy || reading}
          onChange={async (event) => {
            const files = Array.from(event.target.files ?? []);
            event.target.value = "";
            setError(null);
            setReading(true);
            onReading(true);
            try {
              if (attachments.length + files.length > 4)
                throw new Error("Attach up to four text files.");
              const added = await Promise.all(
                files.map(async (file) => {
                  if (file.size > 16000)
                    throw new Error(`${file.name} exceeds 16 KB.`);
                  const content = new TextDecoder("utf-8", {
                    fatal: true,
                  }).decode(await file.arrayBuffer());
                  if (content.includes("\0"))
                    throw new Error(
                      `${file.name} is not a supported text file.`,
                    );
                  return { name: file.name, content };
                }),
              );
              const next = [...attachments, ...added];
              if (new Set(next.map((item) => item.name)).size !== next.length)
                throw new Error("Choose files with unique names.");
              if (
                next.reduce(
                  (size, item) =>
                    size + new TextEncoder().encode(item.content).length,
                  0,
                ) > 24000
              )
                throw new Error("Combined attachments exceed 24 KB.");
              onChange(next);
            } catch (cause) {
              setError(
                cause instanceof Error
                  ? cause
                  : new Error("Could not read text files."),
              );
            } finally {
              setReading(false);
              onReading(false);
            }
          }}
        />
      </label>
      <p className="muted">
        UTF-8 text/code only: four files, 16 KB each, 24 KB total. Sent to the
        selected local model when you send the message.
      </p>
      <ErrorNotice error={error} />
      {attachments.map((item) => (
        <div key={item.name} className="panel content-panel">
          <div className="row spread">
            <strong>{item.name}</strong>
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                onChange(attachments.filter((other) => other !== item))
              }
              aria-label={`Remove ${item.name}`}
            >
              Remove
            </button>
          </div>
          <details>
            <summary>Preview text</summary>
            <pre className="log-block">{item.content}</pre>
          </details>
        </div>
      ))}
    </div>
  );
}
