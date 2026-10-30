import { useQuery } from "@tanstack/react-query";
import { accountEpoch, activeStorageAccount } from "./lib/account-storage";

export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function requireCurrentAccount(epoch: number) {
  if (epoch !== accountEpoch())
    throw new Error("Account changed; previous request discarded.");
}

export function streamNeedsAuthentication(event?: Event) {
  try {
    return (
      JSON.parse((event as MessageEvent<string>)?.data ?? "{}")
        .authentication_required === true
    );
  } catch {
    return false;
  }
}

async function privateResponse(path: string, options?: RequestInit) {
  const epoch = accountEpoch();
  const owner = activeStorageAccount();
  let headers = options?.headers;
  if (owner && !path.startsWith("/auth")) {
    headers = new Headers(headers);
    headers.set("X-AI-Station-Account", owner);
  }
  // Account-private reads never reuse a browser cache. Before account login,
  // auth responses already carry no-store; keep the existing operator client
  // contract (an ordinary GET has no request options) during staged rollout.
  const response = await fetch(
    `/api${path}`,
    owner
      ? {
          ...options,
          ...(headers ? { headers } : {}),
          cache: "no-store",
        }
      : options,
  );
  requireCurrentAccount(epoch);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    requireCurrentAccount(epoch);
    if (
      (response.status === 401 &&
        !path.startsWith("/auth") &&
        !path.startsWith("/operator-auth")) ||
      response.headers?.get?.("X-AI-Station-Account-Changed") === "true"
    )
      window.dispatchEvent(new Event("ai-station:session-expired"));
    throw new ApiError(
      typeof body.detail === "string"
        ? body.detail
        : Array.isArray(body.detail)
          ? body.detail
              .map((issue: { msg?: string }) => issue.msg ?? "Invalid input")
              .join("; ")
          : `Request failed (${response.status})`,
      response.status,
    );
  }
  return { response, epoch };
}

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const { response, epoch } = await privateResponse(path, options);
  if (response.status === 204) return undefined as T;
  const body = await response.json();
  requireCurrentAccount(epoch);
  return body as T;
}

export async function apiText(path: string) {
  const { response, epoch } = await privateResponse(path);
  const body = await response.text();
  requireCurrentAccount(epoch);
  return body;
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
export interface ResourceWait {
  run_id: string;
  reason: "memory" | "gpu";
  checked_at: string;
  required_mib: number;
  available_mib: number | null;
  reserved_mib: number;
  headroom_mib: number;
}
export interface Run {
  id: string;
  project_id: string | null;
  agent_id?: string | null;
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
  resource_wait?: ResourceWait | null;
  parameters: Record<string, unknown>;
  effective_permissions: string[];
  summary: string;
  error_type: string;
  error_message: string;
  worker_id: string | null;
  runner_id?: string | null;
  pid?: number | null;
  process_group_id?: number | null;
  metadata?: Record<string, unknown>;
  approval?: {
    id: string;
    action: string;
    reason: string;
    risk: string;
    payload: Record<string, unknown>;
    requested_at: string;
    resolved_at: string | null;
    resolution: string;
  };
  retry?: {
    allowed: boolean;
    retry_run_id?: string | null;
    retry_of?: string | null;
  };
  workflow?: {
    parent_run_id: string;
    mode: string;
    tool_calling?: string;
    steps: {
      run_id: string;
      key: string;
      gate: string;
      status: string;
      capability: string;
      tool_calls?: {
        id: string;
        tool: string;
        arguments: Record<string, unknown>;
        round: number;
      }[];
      memory_id?: string | null;
      memory_excerpted?: boolean;
    }[];
  };
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
  lease_seconds?: number;
  held_lease_count?: number;
  stale_lease_count?: number;
  leases?: {
    id: string;
    status: string;
    worker_id: string | null;
    executor_type: string;
    retry_class: string;
    lease_expires_at: string | null;
    stale: boolean;
    replay: boolean;
  }[];
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
  title?: string;
  notes?: string;
  library_updated_at?: string | null;
  trashed_at?: string | null;
  purged_at?: string | null;
  purge_run_id?: string | null;
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

export interface ArtifactLineage {
  id: string;
  sources: Artifact[];
  derived: Artifact[];
}
