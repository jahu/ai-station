import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link } from "react-router-dom";
import { version as buildVersion } from "../../package.json";
import { api } from "../api";
import { useAccount } from "../account-context";
import {
  newerVersion,
  type UpdateStatus,
} from "../pages/station-update-contract";
import "./StationVersion.css";

export default function StationVersion() {
  const account = useAccount();
  const cache = useQueryClient();
  const updates = useQuery({
    queryKey: ["station-updates"],
    queryFn: () => api<UpdateStatus>("/maintenance/updates"),
    enabled: account.mode !== "accounts" || !!account.user?.is_admin,
    staleTime: 60000,
    refetchInterval: 15 * 60000,
    retry: false,
  });
  const { mutate: check } = useMutation({
    mutationKey: ["station-updates-check"],
    mutationFn: () =>
      api("/maintenance/updates/checks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      }),
    onSuccess: () => cache.invalidateQueries({ queryKey: ["station-updates"] }),
  });
  useEffect(() => {
    const data = updates.data;
    if (
      !data?.installation?.installed ||
      cache.isMutating({ mutationKey: ["station-updates-check"] })
    )
      return;
    const attempted = data.latest_check?.created_at;
    if (!attempted || Date.now() - Date.parse(attempted) > 4 * 60 * 60000)
      check();
  }, [updates.data, cache, check]);
  const health = useQuery({
    queryKey: ["station-version"],
    queryFn: () => api<{ version: string }>("/health"),
    staleTime: 60000,
    retry: false,
  });
  const version =
    typeof health.data?.version === "string" && health.data.version.trim()
      ? health.data.version
      : buildVersion;
  return (
    <div
      className="station-version"
      aria-label={`AI Station version ${version}`}
      title={`AI Station ${version}`}
    >
      v{version}
      {updates.data?.release &&
        newerVersion(updates.data.release.version, version) && (
          <Link
            to="/settings/updates"
            aria-label={`Update available: AI Station ${updates.data.release.version}`}
            title={`AI Station ${updates.data.release.version} is available`}
          >
            ↑
          </Link>
        )}
    </div>
  );
}
