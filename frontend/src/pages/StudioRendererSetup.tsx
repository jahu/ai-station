import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Check, RefreshCw, Square } from "lucide-react";
import { api, type Run } from "../api";
import { useAccount } from "../account-context";
import { Badge, ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";
import { creativeJson } from "../components/creative/creative-project";
import { randomId } from "../lib/random-id";
import { terminal } from "./studio-production";

const profile = "hyperframes-cpu-linux-amd64-v1";
const base = "/setup/runtimes";
const suffix = "?profile=" + profile;
type Catalog = {
  can_prepare: boolean;
  installation_available: boolean;
  installation_notice?: string;
  usable_image?: boolean;
  manifest_sha256: string;
  image?: { present?: boolean };
  recipe?: { license: string; license_url: string; preparation_mode?: string };
};
type Preparation = {
  id: string;
  manifest_sha256: string;
  run: Run;
  resume_allowed: boolean;
  progress?: { phase?: string };
};

export default function StudioRendererSetup() {
  const { user } = useAccount();
  const cache = useQueryClient();
  const key = ["studio-renderer-setup", user?.id];
  const catalog = useQuery({
    queryKey: [...key, "catalog"],
    queryFn: ({ signal }) => api<Catalog>(base + suffix, { signal }),
  });
  const history = useQuery({
    queryKey: [...key, "history"],
    queryFn: ({ signal }) =>
      api<Preparation[]>(base + "/preparations" + suffix, { signal }),
    refetchInterval: (q) =>
      q.state.data?.some((p) => !terminal.has(p.run.status)) ? 1000 : false,
  });
  const [accepted, setAccepted] = useState("");
  const receipt = useRef<{ fingerprint: string; id: string } | null>(null);
  const completed = useRef(new Set<string>());
  const active = history.data?.find((p) => !terminal.has(p.run.status));
  const current = active ?? history.data?.[0];
  const data = catalog.data;
  const fresh =
    data?.recipe?.preparation_mode === "owned_containers" &&
    !data.image?.present;
  const phases: Record<string, string> = {
    bases: "Downloading runtime components",
    sdk: "Preparing the animation toolkit",
    runtime: "Preparing video and audio tools",
    assembling: "Assembling the export engine",
    verifying: "Verifying the export engine",
  };
  const phase = phases[current?.progress?.phase ?? ""];
  const resumable =
    current?.resume_allowed &&
    current.manifest_sha256 === data?.manifest_sha256;
  function refresh() {
    void cache.invalidateQueries({ queryKey: key });
    void cache.invalidateQueries({ queryKey: ["studio-renderer"] });
  }
  useEffect(() => {
    for (const p of history.data ?? []) {
      if (terminal.has(p.run.status) && !completed.current.has(p.run.id)) {
        completed.current.add(p.run.id);
        void cache.invalidateQueries({
          queryKey: ["studio-renderer-setup", user?.id, "catalog"],
        });
        void cache.invalidateQueries({ queryKey: ["studio-renderer"] });
      }
    }
  }, [history.data, cache, user?.id]);
  const action = useMutation({
    mutationFn: (kind: "prepare" | "cancel" | "resume") => {
      if (kind === "cancel" && active)
        return api(
          base + "/preparations/" + active.id + "/cancel",
          creativeJson("POST", {}),
        );
      if (!data?.installation_available || accepted !== data.manifest_sha256)
        throw new Error("Review the current export engine before preparation.");
      const fingerprint =
        kind +
        ":" +
        data.manifest_sha256 +
        ":" +
        (kind === "resume" ? current?.run.id : "");
      if (receipt.current?.fingerprint !== fingerprint)
        receipt.current = { fingerprint, id: randomId() };
      if (kind === "resume") {
        if (!resumable || !current)
          throw new Error("This activation cannot be resumed.");
        return api(
          base + "/preparations/" + current.id + "/resume",
          creativeJson("POST", {
            client_request_id: receipt.current.id,
            expected_run_id: current.run.id,
          }),
        );
      }
      return api(
        base,
        creativeJson("POST", {
          client_request_id: receipt.current.id,
          profile,
          manifest_sha256: data.manifest_sha256,
          license_accepted: true,
        }),
      );
    },
    onSuccess: refresh,
  });
  return (
    <section className="studio-renderer-setup" aria-label="Film export setup">
      <div>
        <strong>
          {data?.usable_image ? "Film export is ready" : "Prepare film export"}
        </strong>
        <p className="studio-direction-note">
          {data?.usable_image
            ? "Your local export engine is ready to assemble the selected shots and soundtrack."
            : "Export your finished story as a Full-HD MP4 on this station. Preparing export keeps your shots and soundtrack."}
        </p>
      </div>
      {data?.installation_notice && !data.usable_image && (
        <p className="studio-direction-note">{data.installation_notice}</p>
      )}
      {data?.usable_image && (
        <p className="studio-renderer-ready">
          <Check size={16} /> Ready on this station
        </p>
      )}
      {!data?.can_prepare && data && !data.usable_image && (
        <p className="studio-direction-note">
          Ask a station administrator to prepare film export.
        </p>
      )}
      {data?.can_prepare &&
        data.installation_available &&
        !data.usable_image &&
        !active && (
          <>
            <label className="studio-renderer-consent">
              <input
                type="checkbox"
                checked={accepted === data.manifest_sha256}
                onChange={(e) =>
                  setAccepted(e.target.checked ? data.manifest_sha256 : "")
                }
              />
              <span>
                {fresh
                  ? "Download and prepare the local export engine using your CPU. Your other apps and AI models stay unchanged. Download size depends on cached components."
                  : "Activate the compatible export engine already installed on this station. No model downloads or GPU use."}
              </span>
            </label>
            {data.recipe && (
              <details>
                <summary>Component licenses</summary>
                <p className="studio-direction-note">{data.recipe.license}</p>
                <a
                  href={data.recipe.license_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Read renderer license ↗
                </a>
              </details>
            )}
            <Button
              type="button"
              disabled={action.isPending || accepted !== data.manifest_sha256}
              onClick={() => action.mutate(resumable ? "resume" : "prepare")}
            >
              {resumable
                ? fresh
                  ? "Retry preparation"
                  : "Retry activation"
                : fresh
                  ? "Prepare film export"
                  : "Activate film export"}
            </Button>
          </>
        )}
      {current && (
        <div className="studio-export-progress" role="status">
          <div>
            <strong>
              {active
                ? phase ||
                  (fresh ? "Preparing film export" : "Activating film export")
                : current.run.status === "succeeded"
                  ? "Film export prepared"
                  : "Preparation stopped"}
            </strong>
            {current.run.error_message && (
              <span>{current.run.error_message}</span>
            )}
          </div>
          <Badge status={current.run.status} />
          {active && data?.can_prepare && (
            <Button
              type="button"
              variant="ghost"
              disabled={action.isPending}
              onClick={() => action.mutate("cancel")}
            >
              <Square size={13} />{" "}
              {fresh || phase ? "Stop preparation" : "Stop activation"}
            </Button>
          )}
          <Link to={`/runs/${current.run.id}`}>Details & logs ↗</Link>
        </div>
      )}
      <ErrorNotice error={catalog.error ?? history.error ?? action.error} />
      <Button
        type="button"
        variant="ghost"
        disabled={catalog.isFetching || history.isFetching}
        onClick={refresh}
      >
        <RefreshCw size={14} /> Check again
      </Button>
    </section>
  );
}
