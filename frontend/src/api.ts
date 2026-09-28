import { useQuery } from "@tanstack/react-query";

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : Array.isArray(body.detail)
          ? body.detail
              .map((issue: { msg?: string }) => issue.msg ?? "Invalid input")
              .join("; ")
          : `Request failed (${response.status})`,
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export interface GPU {
  index: number;
  uuid: string;
  name: string;
  utilization: number | null;
  memory_used_mib: number | null;
  memory_total_mib: number | null;
  temperature_c: number | null;
  fan_percent: number | null;
  power_watts: number | null;
}
export interface Hardware {
  gpus: GPU[];
  cpu: { utilization: number | null; temperature_c: number | null };
  memory: {
    total_mib: number;
    used_mib: number;
    available_mib: number;
    swap_used_mib: number;
    swap_total_mib: number;
  };
  disk: { total_bytes: number; used_bytes: number; free_bytes: number };
  load: Record<string, number>;
}
export interface Run {
  id: string;
  project_id: string | null;
  task_id: string;
  parent_run_id: string | null;
  capability: string;
  executor_type: string;
  execution_target: string;
  status: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  actual_gpu: string | null;
  requested_gpu: string;
  parameters: Record<string, unknown>;
  effective_permissions: string[];
  summary: string;
  error_message: string;
  worker_id: string | null;
  metadata?: Record<string, unknown>;
}
export interface RunEvent {
  id: string;
  sequence: number;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
}
export interface Sample {
  sampled_at: string;
  payload: Partial<Hardware>;
  resolution: string;
}
export interface Diagnostic {
  name: string;
  status: string;
  detail: string;
}
export interface Status {
  counts: Record<string, number>;
  workers: { id: string; available: boolean; last_heartbeat: string }[];
  scheduler: { available: boolean; last_heartbeat: string | null };
}

export function useHardware() {
  return useQuery({
    queryKey: ["hardware"],
    queryFn: () => api<Hardware>("/system/hardware"),
    refetchInterval: 5000,
  });
}
export function useRuns(status = "", filters: Record<string, string> = {}) {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value);
  }
  const search = params.toString();
  return useQuery({
    queryKey: ["runs", status, search],
    queryFn: () => api<Run[]>(`/runs${search ? `?${search}` : ""}`),
    refetchInterval: 5000,
  });
}
export function useStatus() {
  return useQuery({
    queryKey: ["status"],
    queryFn: () => api<Status>("/system/status"),
    refetchInterval: 5000,
  });
}

export interface Artifact {
  id: string;
  type: string;
  mime_type: string;
  original_filename: string;
  size_bytes: number;
  created_at: string;
  run_id: string | null;
  parent_artifact_ids: string[];
  metadata: {
    text?: string;
    duration_seconds?: number;
    width?: number;
    height?: number;
    mode?: string;
    backend?: string;
    prompt?: string;
    edit_prompt?: string;
    [key: string]: unknown;
  };
}
