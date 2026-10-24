export type DocumentScope = {
  artifact_ids: string[];
  snapshots?: {
    artifact_id: string;
    sha256: string;
    size_bytes: number;
    mime_type: string;
    name: string;
  }[];
};
export const DOCUMENT_MIMES = [
  "application/pdf",
  "text/plain",
  "text/markdown",
];
export function canReadDocument(mime: string, size: number) {
  return (
    DOCUMENT_MIMES.includes(mime) &&
    size > 0 &&
    size <= (mime === "application/pdf" ? 8 * 1024 ** 2 : 256 * 1024)
  );
}
export function initialDocumentToolMode(
  tools: string[],
  current: DocumentScope | null | undefined,
  mode: "none" | "bounded" = "none",
) {
  return !current &&
    !tools.some((name) =>
      [
        "python_data",
        "coding_local",
        "coding_cursor",
        "coding_codex",
        "create_media",
      ].includes(name),
    )
    ? "bounded"
    : mode;
}

export type DocumentObservation = {
  artifact_id: string;
  captured_at: string;
  query?: string;
  offset?: number;
  documents: {
    source_artifact_id: string;
    text_artifact_id: string;
    name: string;
    text: string;
    page_count: number;
    truncated: boolean;
    excerpted: boolean;
    query_found?: boolean;
  }[];
};
export function documentObservation(
  value: unknown,
): value is DocumentObservation {
  if (!value || typeof value !== "object") return false;
  const data = value as Record<string, unknown>;
  return (
    typeof data.artifact_id === "string" &&
    typeof data.captured_at === "string" &&
    Array.isArray(data.documents) &&
    data.documents.length > 0 &&
    data.documents.length <= 4 &&
    data.documents.every(
      (doc) =>
        doc &&
        typeof doc === "object" &&
        typeof doc.source_artifact_id === "string" &&
        typeof doc.text_artifact_id === "string" &&
        typeof doc.name === "string" &&
        typeof doc.text === "string" &&
        typeof doc.page_count === "number" &&
        typeof doc.truncated === "boolean" &&
        typeof doc.excerpted === "boolean",
    )
  );
}
