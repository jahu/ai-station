import { useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { Download } from "lucide-react";
import { api } from "../api";
import { ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";
import { randomId } from "../lib/random-id";
import { PreparationCard, type Preparation } from "./ModelSetup";

export type InstallPlan = {
  manifest_sha256: string;
  license: string;
  license_url: string;
  files: {
    assessment: { hardware_status: string; disk: { status: string } };
  }[];
};
type DownloadState = Preparation & { manifest_sha256: string };
const post = (body: unknown) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
const terminal = ["succeeded", "failed", "interrupted", "canceled"];

export default function HubInstallPanel({
  plan,
  runId,
  canManage,
  downloadId,
  onDownload,
}: {
  plan: InstallPlan;
  runId: string;
  canManage: boolean;
  downloadId: string;
  onDownload: (id: string) => void;
}) {
  const [accepted, setAccepted] = useState(false);
  const receipt = useRef<string | null>(null);
  const navigate = useNavigate();
  const download = useQuery({
    queryKey: ["hub-download", downloadId],
    enabled: !!downloadId,
    queryFn: async ({ signal }) => {
      const state = await api<DownloadState>(`/setup/downloads/${downloadId}`, {
        signal,
      });
      if (state.manifest_sha256 !== plan.manifest_sha256)
        throw new Error(
          "This download belongs to another reviewed model plan.",
        );
      return state;
    },
    refetchInterval: (q) =>
      q.state.data && terminal.includes(q.state.data.run.status) ? false : 1000,
  });
  const install = useMutation({
    mutationFn: () => {
      if (!receipt.current) receipt.current = randomId();
      return api<DownloadState>(
        "/model-hub/downloads",
        post({
          client_request_id: receipt.current,
          plan_run_id: runId,
          manifest_sha256: plan.manifest_sha256,
          license_accepted: accepted,
        }),
      );
    },
    onSuccess: (state) => onDownload(state.id),
  });
  const chat = useMutation({
    mutationFn: (model: string) =>
      api<{ id: string }>(
        "/chat/conversations",
        post({ model, execution_mode: "assistant" }),
      ),
    onSuccess: (conversation) => navigate(`/chat/${conversation.id}`),
  });
  const fit = plan.files[0]?.assessment;
  const allowed =
    fit?.hardware_status === "estimated_fit" && fit.disk.status === "file_fits";
  return (
    <section className="panel hub-install" aria-label="Install reviewed model">
      <h2>
        {downloadId ? "Model preparation" : "Ready to review and install"}
      </h2>
      <p className="muted">
        AI Station checks the download and fits the model to your GPUs before
        adding it to Chat. Open a conversation when preparation is complete.
      </p>
      {!downloadId && (
        <>
          <label className="hub-license">
            <input
              type="checkbox"
              checked={accepted}
              onChange={(e) => setAccepted(e.target.checked)}
              disabled={!canManage || install.isPending}
            />
            <span>
              I have reviewed the source and{" "}
              <a href={plan.license_url} target="_blank" rel="noreferrer">
                model license ({plan.license})
              </a>{" "}
              and agree to download this model.
            </span>
          </label>
          <Button
            disabled={!canManage || !accepted || !allowed || install.isPending}
            onClick={() => install.mutate()}
          >
            <Download size={16} />
            {install.isPending ? "Starting preparation…" : "Install model"}
          </Button>
          {!allowed && (
            <p className="muted">
              Choose a fitting model or refresh the hardware plan after freeing
              resources or storage.
            </p>
          )}
        </>
      )}
      <ErrorNotice error={install.error ?? download.error ?? chat.error} />
      {download.data && (
        <PreparationCard
          value={download.data}
          canPrepare={canManage}
          refresh={() => void download.refetch()}
          onOpen={(model) => chat.mutate(model)}
          opening={chat.isPending}
        />
      )}
      <Link className="text-link" to="/setup/models">
        All model preparations & engine setup →
      </Link>
    </section>
  );
}
