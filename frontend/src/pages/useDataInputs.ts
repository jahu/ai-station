import { useQueries } from "@tanstack/react-query";
import { api, type Artifact, type Run } from "../api";
import type { DataScope } from "./AgentDataFiles";
import { canReadDocument, type DocumentScope } from "./document-context";

export type ConversationDataScope = DataScope & {
  documents?: DocumentScope | null;
  research?: {
    search_query: string;
    fetch_urls: string[];
    read_search_pages: boolean;
    render_pages?: boolean;
  };
  model?: string;
  maximum_runtime?: number;
};
const terminal = new Set(["succeeded", "failed", "canceled", "interrupted"]);
function researchDataReady(scope?: ConversationDataScope | null) {
  const source = scope?.research;
  if (!source) return false;
  return (
    (source.search_query.trim().length > 0 || source.fetch_urls.length > 0) &&
    source.search_query.length <= 500 &&
    source.fetch_urls.length <= 3 &&
    source.fetch_urls.every((url) => {
      try {
        const value = new URL(url);
        return (
          ["http:", "https:"].includes(value.protocol) &&
          !!value.hostname &&
          !value.username &&
          !value.password
        );
      } catch {
        return false;
      }
    }) &&
    (!source.read_search_pages || !!source.search_query.trim()) &&
    (!source.render_pages || source.fetch_urls.length > 0)
  );
}
export function useDataInputs(scope?: ConversationDataScope | null) {
  const ids = scope?.input_artifact_ids ?? [];
  const files = useQueries({
    queries: ids.map((id) => ({
      queryKey: ["artifact", id],
      queryFn: () => api<Artifact>(`/artifacts/${id}`),
    })),
  });
  const documentIds = scope?.documents?.artifact_ids ?? [];
  const documents = useQueries({
    queries: documentIds.map((id) => ({
      queryKey: ["artifact", id],
      queryFn: () => api<Artifact>(`/artifacts/${id}`),
    })),
  });
  const documentReady =
    !scope?.documents ||
    (documentIds.length > 0 &&
      documentIds.length <= 4 &&
      new Set(documentIds).size === documentIds.length &&
      documents.every(
        (query) =>
          query.data &&
          !query.data.trashed_at &&
          canReadDocument(query.data.mime_type, query.data.size_bytes),
      ));
  const inspections = useQueries({
    queries: files.map((file) => {
      const id = file.data?.metadata?.data_inspection_run_id as
        string | undefined;
      return {
        queryKey: ["run", id],
        queryFn: () => api<Run>(`/runs/${id}`),
        enabled: !!id,
        refetchInterval: (query: { state: { data: Run | undefined } }) =>
          query.state.data && terminal.has(query.state.data.status)
            ? false
            : 1000,
      };
    }),
  });
  const states = ids.map((id, index) => {
    const file = files[index];
    const inspection = inspections[index];
    const run = inspection?.data;
    const ready =
      !!file?.data &&
      !file.data.trashed_at &&
      run?.status === "succeeded" &&
      !!run.metadata?.preview_artifact_id;
    return {
      id,
      file: file?.data,
      run,
      ready,
      error: file?.error ?? inspection?.error,
      label: file?.data?.trashed_at
        ? "File is in Trash"
        : file?.error || inspection?.error
          ? "Unable to check file"
          : !file?.data
            ? "Loading file…"
            : !file.data.metadata?.data_inspection_run_id
              ? "Inspection needed"
              : ready
                ? "Ready for analysis"
                : run && terminal.has(run.status)
                  ? "Inspection unsuccessful"
                  : "Inspecting file…",
    };
  });
  return {
    states,
    ready:
      (scope?.operation === "create"
        ? ids.length === 0 && !scope.research && !scope.documents
        : scope?.documents || scope?.research
          ? documentReady &&
            (!scope?.research || researchDataReady(scope)) &&
            ids.length <= 7
          : ids.length > 0 && ids.length <= 8) &&
      states.every((item) => item.ready),
  };
}
