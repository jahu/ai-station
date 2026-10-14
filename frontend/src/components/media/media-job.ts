import { useQuery } from "@tanstack/react-query";
import { api } from "../../api";

export type MediaJob = {
  task_id: string;
  revision: number;
  status: string;
  kind: string;
  mode: string;
  duration_seconds: number | null;
  completed_segments: number;
  total_segments: number;
  final_artifact_id: string | null;
  active_run_ids: string[];
  resume_allowed: boolean;
  error_message: string;
};
export const jobBusy = (job?: MediaJob) =>
  !!job &&
  (!!job.active_run_ids?.length ||
    !["succeeded", "failed", "canceled", "interrupted"].includes(job.status));
export function useMediaJob(id: string) {
  return useQuery({
    queryKey: ["media-job", id],
    queryFn: () => api<MediaJob>(`/media/jobs/${id}`),
    enabled: !!id,
    refetchInterval: (query) =>
      query.state.data && !jobBusy(query.state.data) ? false : 1500,
  });
}
