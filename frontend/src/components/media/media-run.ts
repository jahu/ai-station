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

export function useImageWorkflow(run: Run | undefined) {
  const enabled = !!run?.parameters?.upscale_result;
  return useQuery({
    queryKey: ["image-workflow", run?.id],
    queryFn: () => api<{ steps: Run[] }>(`/images/runs/${run!.id}/workflow`),
    enabled,
    refetchInterval: (query) => {
      const last = query.state.data?.steps.at(-1);
      return last && terminal.has(last.status) ? false : 1500;
    },
  });
}
