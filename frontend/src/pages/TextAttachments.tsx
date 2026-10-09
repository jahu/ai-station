import { useId, useRef, useState, type KeyboardEvent } from "react";
import { Paperclip } from "lucide-react";
import { Button } from "../components/ui/button";
import { ErrorNotice } from "../components/common";
import { useListKeyboard } from "./useListKeyboard";

export type TextAttachment = {
  name: string;
  content: string;
  kind?: "text" | "pdf" | "image";
};

function kindOf(file: File): NonNullable<TextAttachment["kind"]> {
  const name = file.name.toLowerCase();
  if (file.type === "application/pdf" || name.endsWith(".pdf")) return "pdf";
  if (
    /image\/(png|jpeg|webp)/.test(file.type) ||
    /\.(png|jpe?g|webp)$/.test(name)
  )
    return "image";
  return "text";
}

function AttachmentCards({
  attachments,
  busy,
  onChange,
}: {
  attachments: TextAttachment[];
  busy: boolean;
  onChange: (items: TextAttachment[]) => void;
}) {
  const labelId = useId();
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    attachments,
    (item) => item.name,
  );
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown(event);
    if (event.key === "Enter") event.preventDefault();
  };
  return (
    <>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose an attachment while the list is focused. Remove stays
        on the selected file. Enter does not send. There is no inspectable
        attachment Run.
      </p>
      <div
        ref={listRef}
        className="chat-attachment-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {attachments.map((item, i) => {
          const current = i === index;
          return (
            <div
              key={item.name}
              className="panel content-panel"
              aria-label={`Attachment ${item.name}`}
              {...itemProps(i, item.name)}
            >
              <div className="row spread">
                <strong>{item.name}</strong>
                <button
                  type="button"
                  disabled={busy}
                  tabIndex={current ? 0 : -1}
                  onClick={() =>
                    onChange(attachments.filter((other) => other !== item))
                  }
                  aria-label={`Remove ${item.name}`}
                >
                  Remove
                </button>
              </div>
              {(item.kind ?? "text") === "text" && (
                <details>
                  <summary>Preview {item.name}</summary>
                  <pre className="log-block">{item.content}</pre>
                </details>
              )}
              {item.kind === "pdf" && (
                <p className="muted">
                  PDF · text will be extracted when you send
                </p>
              )}
              {item.kind === "image" && (
                <>
                  <p className="muted">
                    Image stored with the message. Pixels are not sent to the
                    model.
                  </p>
                  <img
                    className="chat-attachment-preview"
                    alt={item.name}
                    src={`data:${imageMime(item.name)};base64,${item.content}`}
                  />
                </>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}

function imageMime(name: string) {
  const lower = name.toLowerCase();
  if (lower.endsWith(".png")) return "image/png";
  if (lower.endsWith(".webp")) return "image/webp";
  return "image/jpeg";
}

function toBase64(buffer: ArrayBuffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

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
  const input = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<Error | null>(null);
  const [reading, setReading] = useState(false);
  return (
    <div className="chat-text-attachments">
      <Button
        type="button"
        variant="ghost"
        disabled={busy || reading}
        onClick={() => input.current?.click()}
      >
        <Paperclip size={15} />{" "}
        {reading ? "Reading files…" : "Attach text, PDF, or image"}
      </Button>
      <input
        ref={input}
        hidden
        aria-label="Attach files"
        type="file"
        multiple
        accept=".pdf,image/png,image/jpeg,image/webp,text/*,.md,.py,.json,.txt,.html,.css,.js,.ts,.tsx"
        disabled={busy || reading}
        onChange={async (event) => {
          const files = Array.from(event.target.files ?? []);
          event.target.value = "";
          setError(null);
          setReading(true);
          onReading(true);
          try {
            if (attachments.length + files.length > 4)
              throw new Error("Attach up to four files.");
            const added = await Promise.all(
              files.map(async (file) => {
                const kind = kindOf(file);
                if (kind === "pdf") {
                  if (file.size > 1024 * 1024)
                    throw new Error(`${file.name} exceeds 1 MiB.`);
                  return {
                    name: file.name,
                    kind,
                    content: toBase64(await file.arrayBuffer()),
                  };
                }
                if (kind === "image") {
                  if (file.size > 2 * 1024 * 1024)
                    throw new Error(`${file.name} exceeds 2 MiB.`);
                  if (
                    !/image\/(png|jpeg|webp)/.test(file.type) &&
                    !/\.(png|jpe?g|webp)$/i.test(file.name)
                  )
                    throw new Error(`${file.name} is not a supported image.`);
                  return {
                    name: file.name,
                    kind,
                    content: toBase64(await file.arrayBuffer()),
                  };
                }
                if (file.size > 16000)
                  throw new Error(`${file.name} exceeds 16 KB.`);
                const content = new TextDecoder("utf-8", {
                  fatal: true,
                }).decode(await file.arrayBuffer());
                if (content.includes("\0"))
                  throw new Error(`${file.name} is not a supported text file.`);
                return { name: file.name, kind: "text" as const, content };
              }),
            );
            const next = [...attachments, ...added];
            if (new Set(next.map((item) => item.name)).size !== next.length)
              throw new Error("Choose files with unique names.");
            const textBytes = next
              .filter((item) => (item.kind ?? "text") === "text")
              .reduce(
                (size, item) =>
                  size + new TextEncoder().encode(item.content).length,
                0,
              );
            if (textBytes > 24000)
              throw new Error("Combined text attachments exceed 24 KB.");
            onChange(next);
          } catch (cause) {
            setError(
              cause instanceof Error
                ? cause
                : new Error("Could not read the selected files."),
            );
          } finally {
            setReading(false);
            onReading(false);
          }
        }}
      />
      <details className="chat-attachment-help">
        <summary>Supported files and privacy</summary>
        <p className="muted">
          Up to four files. UTF-8 text/code: 16 KB each, 24 KB total. PDFs: 1
          MiB and 8 pages; only extractable text is sent, not a visual reading.
          PNG/JPEG/WebP: 2 MiB and 4 megapixels; pixels are stored as artifacts
          and are not sent to this text model. Vision remains unavailable.
        </p>
      </details>
      <ErrorNotice error={error} />
      {attachments.length > 0 && (
        <AttachmentCards
          attachments={attachments}
          busy={busy}
          onChange={onChange}
        />
      )}
    </div>
  );
}
