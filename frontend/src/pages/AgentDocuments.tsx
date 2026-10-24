import { useEffect, useId, useRef } from "react";
import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { FileText, Upload, X } from "lucide-react";
import { api, type Artifact } from "../api";
import { ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";
import LibraryPicker from "../components/media/LibraryPicker";
import type { DocumentScope } from "./document-context";

export default function AgentDocuments({
  value,
  disabled,
  onChange,
  onUploading,
  context = "agent",
}: {
  value?: DocumentScope | null;
  disabled: boolean;
  onChange: (value: DocumentScope | null) => void;
  onUploading?: (busy: boolean) => void;
  context?: "agent" | "analysis";
}) {
  const id = useId(),
    file = useRef<HTMLInputElement>(null),
    cache = useQueryClient();
  const ids = value?.artifact_ids ?? [];
  const queries = useQueries({
    queries: ids.map((aid) => ({
      queryKey: ["artifact", aid],
      queryFn: () => api<Artifact>(`/artifacts/${aid}`),
    })),
  });
  const update = (next: string[]) =>
    onChange(next.length ? { artifact_ids: next } : null);
  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      if (files.length + ids.length > 4)
        throw new Error("Choose up to four documents.");
      if (files.some((f) => !/\.(pdf|txt|md)$/i.test(f.name)))
        throw new Error("Choose PDF, UTF-8 text or Markdown documents.");
      if (
        files.some(
          (f) =>
            !f.size ||
            f.size > (/\.pdf$/i.test(f.name) ? 8 * 1024 ** 2 : 256 * 1024),
        )
      )
        throw new Error("Use PDF up to 8 MB or text/Markdown up to 256 KB.");
      const added: Artifact[] = [];
      try {
        for (const f of files) {
          const body = new FormData();
          body.append("file", f);
          const a = await api<Artifact>("/documents/uploads", {
            method: "POST",
            body,
          });
          added.push(a);
          cache.setQueryData(["artifact", a.id], a);
        }
      } finally {
        if (added.length) update([...ids, ...added.map((a) => a.id)]);
        void cache.invalidateQueries({ queryKey: ["library"] });
      }
    },
  });
  useEffect(() => {
    onUploading?.(upload.isPending);
    return () => onUploading?.(false);
  }, [upload.isPending, onUploading]);
  const busy = disabled || upload.isPending;
  return (
    <section
      className="agent-data-files"
      aria-labelledby={id}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        if (!busy) upload.mutate(Array.from(e.dataTransfer.files));
      }}
    >
      <h3 id={id}>
        <FileText size={17} /> Selected documents
      </h3>
      <p className="muted">
        Upload or drop PDFs, text and Markdown, or choose stored files. The{" "}
        {context === "agent"
          ? "agent reads only this selection."
          : "analysis reads only this selection."}{" "}
        Originals stay unchanged.
      </p>
      <div className="row agent-data-actions">
        <input
          ref={file}
          type="file"
          accept=".pdf,.txt,.md"
          multiple
          hidden
          aria-label={
            context === "agent"
              ? "Upload agent documents"
              : "Upload analysis documents"
          }
          disabled={busy || ids.length >= 4}
          onChange={(e) => {
            const selected = Array.from(e.target.files ?? []);
            e.target.value = "";
            if (selected.length) upload.mutate(selected);
          }}
        />
        <Button
          type="button"
          variant="secondary"
          disabled={busy || ids.length >= 4}
          onClick={() => file.current?.click()}
        >
          <Upload size={15} />
          {upload.isPending ? "Uploading…" : "Upload documents"}
        </Button>
        <LibraryPicker
          kind="document"
          documentMode="reference"
          existing={ids}
          limit={4 - ids.length}
          busy={busy}
          onSelect={(items) => update([...ids, ...items.map((a) => a.id)])}
        />
      </div>
      {ids.length ? (
        <ul className="data-input-list">
          {ids.map((aid, i) => {
            const a = queries[i].data;
            const name =
              a?.title ||
              a?.original_filename ||
              value?.snapshots?.find((s) => s.artifact_id === aid)?.name ||
              "Loading document…";
            return (
              <li key={aid}>
                <Link className="text-link" to={`/library/${aid}`}>
                  {name}
                </Link>
                <Button
                  type="button"
                  variant="ghost"
                  disabled={busy}
                  aria-label={`Remove document ${name}`}
                  onClick={() => update(ids.filter((i) => i !== aid))}
                >
                  <X size={15} />
                </Button>
                {a?.trashed_at && (
                  <span className="notice">
                    This document is in Trash. Restore it or choose another
                    file.
                  </span>
                )}
                <ErrorNotice error={queries[i].error} />
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="muted">
          {context === "agent"
            ? "Choose documents before enabling this tool."
            : "Choose documents to supply text to this analysis."}
        </p>
      )}
      <p className="muted">
        Up to 4 files · PDF: 8 MB, 64 pages · text: 256 KB. Text extraction is
        bounded and excerpts are identified. Scanned PDFs need OCR.
      </p>
      <ErrorNotice error={upload.error} />
    </section>
  );
}
