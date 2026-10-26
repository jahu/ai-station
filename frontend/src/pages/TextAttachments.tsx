import { isImageFile } from "./image-upload";
import { isRecordingFile } from "./recording-upload";
import { isDataFile } from "./data-upload";
import { useId, useRef, useState, type KeyboardEvent } from "react";
import { Paperclip } from "lucide-react";
import { Button } from "../components/ui/button";
import { ErrorNotice } from "../components/common";
import { useListKeyboard } from "./useListKeyboard";
import ComposerAttachments from "./ComposerAttachments";

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
      <p id={labelId} className="sr-only">
        Attached files. Use arrow keys to move between files. Remove acts on the
        selected file.
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
  onDataFiles,
  onImageFiles,
  onRecordingFiles,
  uploadErrorsHandled = false,
}: {
  attachments: TextAttachment[];
  onChange: (items: TextAttachment[]) => void;
  busy: boolean;
  onReading: (reading: boolean) => void;
  onDataFiles?: (files: File[]) => Promise<unknown>;
  onImageFiles?: (files: File[]) => Promise<unknown>;
  onRecordingFiles?: (files: File[]) => Promise<unknown>;
  uploadErrorsHandled?: boolean;
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
        {reading
          ? "Reading files…"
          : onDataFiles || onImageFiles || onRecordingFiles
            ? "Attach files"
            : "Attach text, PDF, or image"}
      </Button>
      <input
        ref={input}
        hidden
        aria-label="Attach files"
        type="file"
        multiple
        accept={
          ".pdf,image/png,image/jpeg,image/webp,text/*,.md,.py,.json,.txt,.html,.css,.js,.ts,.tsx" +
          (onDataFiles ? ",.csv,.xlsx" : "") +
          (onRecordingFiles ? ",.wav,.mp3,.m4a,.ogg,.oga,.webm,.flac" : "")
        }
        disabled={busy || reading}
        onChange={async (event) => {
          const files = Array.from(event.target.files ?? []);
          event.target.value = "";
          setError(null);
          setReading(true);
          onReading(true);
          let delegated = false;
          try {
            if (files.some(isRecordingFile)) {
              if (files.length !== 1 || attachments.length)
                throw new Error(
                  "Choose one recording separately from other attachments. Your existing files are unchanged.",
                );
              if (!onRecordingFiles)
                throw new Error(
                  "Choose Transcribe or Analyze recording in a general conversation to use audio.",
                );
              delegated = true;
              await onRecordingFiles(files);
              return;
            }
            if (files.some(isDataFile)) {
              if (!files.every(isDataFile) || attachments.length)
                throw new Error(
                  "Choose CSV/Excel/JSON separately from text, PDF or image attachments. Your existing files are unchanged.",
                );
              if (!onDataFiles)
                throw new Error(
                  "Choose Files & data in a general conversation to analyse these files locally.",
                );
              delegated = true;
              await onDataFiles(files);
              return;
            }
            if (onImageFiles && files.some(isImageFile)) {
              if (!files.every(isImageFile) || attachments.length)
                throw new Error(
                  "Choose images separately from data, text or PDF attachments. Your existing files are unchanged.",
                );
              delegated = true;
              await onImageFiles(files);
              return;
            }
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
            if (!delegated || !uploadErrorsHandled)
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
        {onRecordingFiles && (
          <p className="muted">
            Audio: one WAV, MP3, M4A, Ogg, WebM or FLAC recording, up to 20 MiB
            and five minutes. Transcription runs locally; summaries and answers
            use your selected conversation model. Choose audio separately from
            other files.
          </p>
        )}
        {onDataFiles && (
          <p className="muted">
            Data: up to eight files, 16 MB each (JSON: 4 MB) and 32 MB total.
            Analysis uses a local model and offline Python; your files stay on
            this station, even with an external conversation provider. Review
            the selected files and Send to start.
          </p>
        )}
        <p className="muted">
          Up to four text/PDF files. UTF-8 text/code: 16 KB each, 24 KB total.
          PDFs: 1 MiB and 8 pages; only extractable text is sent, not a visual
          reading.
        </p>
        {onImageFiles ? (
          <p className="muted">
            Images: up to four PNG/JPEG/WebP files, 20 MiB each. Review their
            order and Send. Local Vision answers image questions; image edits
            and reference generation use the local image tools. Pixels are not
            sent to an external conversation provider.
          </p>
        ) : (
          <p className="muted">
            PNG/JPEG/WebP: 2 MiB and 4 megapixels; pixels are stored as
            artifacts and are not sent to this text model. Choose Inspect images
            for local vision.
          </p>
        )}
      </details>
      <ComposerAttachments>
        <ErrorNotice error={error} />
        {reading && (
          <p className="muted" role="status">
            Reading files…
          </p>
        )}
        {attachments.length > 0 && (
          <AttachmentCards
            attachments={attachments}
            busy={busy}
            onChange={onChange}
          />
        )}
      </ComposerAttachments>
    </div>
  );
}
