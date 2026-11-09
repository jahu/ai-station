import type { Run } from "../api";

export type UpdateStatus = {
  current_version: string;
  latest_check: Run | null;
  checked_at: string | null;
  release: {
    version: string;
    release_url: string;
    notes: string;
    fingerprint?: string;
    packages?: Record<string, { size_bytes: number }>;
  } | null;
  release_check_run_id?: string | null;
  update_run?:
    | (Run & {
        metadata?: {
          native_update?: {
            phase: string;
            downloaded_bytes?: number;
            size_bytes?: number;
          };
          update_apply_requested?: boolean;
        };
      })
    | null;
  apply_available: boolean;
  installation?: { installed: boolean; version?: string; platform?: string };
};

export function newerVersion(candidate: string, current: string) {
  const pattern = /^\d+\.\d+\.\d+$/;
  if (!pattern.test(candidate) || !pattern.test(current)) return false;
  const a = candidate.split(".").map(Number),
    b = current.split(".").map(Number);
  for (let i = 0; i < 3; i++) if (a[i] !== b[i]) return a[i] > b[i];
  return false;
}
