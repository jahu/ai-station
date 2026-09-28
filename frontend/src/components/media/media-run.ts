import { useQuery } from "@tanstack/react-query";
import { api, type Run } from "../../api";

const terminal = new Set(["succeeded", "failed", "canceled", "interrupted"]);
export function useMediaRun(id: string) {
  return useQuery({
    queryKey: ["run", id],
    queryFn: () => api<Run>(`/runs/${id}`),
    enabled: !!id,
    refetchInterval: (query) =>
      query.state.data && terminal.has(query.state.data.status) ? false : 1500,
  });
}
export function mediaBusy(run: Run | undefined) {
  return !!run && !terminal.has(run.status);
}
