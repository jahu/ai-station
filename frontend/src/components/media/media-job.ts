import { useQuery } from "@tanstack/react-query";
import { api, type ResourceWait } from "../../api";

export type MediaRequest = {
  image_artifact_id?: string | null;
  audio_artifact_id?: string;
  speech_text?: string | null;
  prompt?: string;
  negative_prompt?: string;
  size?: number;
  width?: number;
  height?: number;
  steps?: number;
  seed?: number;
  gpu?: string;
  duration_seconds?: number;
  composition_mode?: "continuous" | "shots";
  memory_profile?: "default" | "bounded_11g";
  scenes?: { prompt: string; duration_seconds: number }[] | null;
};
export type MediaJob = {
  resource_wait?: ResourceWait | null;
  request?: MediaRequest;
  preview_artifact_id?: string | null;
  task_id: string;
  revision: number;
  status: string;
  kind: string;
  mode: string;
  scenes?: {
    index: number;
    prompt: string;
    duration_seconds: number;
    status: string;
    completed_segments: number;
    total_segments: number;
  }[];
  duration_seconds: number | null;
  completed_segments: number;
  total_segments: number;
  running_segments?: number;
  queued_segments?: number;
  active_segments?: {
    run_id: string;
    index: number;
    status: string;
    gpu: string | null;
  }[];
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
