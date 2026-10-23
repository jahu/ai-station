import { useQueries } from "@tanstack/react-query";
import { api, type Artifact, type Run } from "../api";
import type { DataScope } from "./AgentDataFiles";

export type ConversationDataScope = DataScope & {
  model?: string;
  maximum_runtime?: number;
};
const terminal = new Set(["succeeded", "failed", "canceled", "interrupted"]);
export function useDataInputs(scope?: DataScope | null) {
  const ids = scope?.input_artifact_ids ?? [];
  const files = useQueries({
    queries: ids.map((id) => ({
      queryKey: ["artifact", id],
      queryFn: () => api<Artifact>(`/artifacts/${id}`),
    })),
  });
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
    ready: ids.length > 0 && states.every((item) => item.ready),
  };
}
