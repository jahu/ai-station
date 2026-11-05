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
  capability?: "chat" | "image" | "video" | "speech" | "embedding";
  components?: { role: string; filename: string; size_bytes: number }[];
  component_licenses?: { name: string; url: string }[];
  license: string;
  license_url: string;
  files: {
    assessment: {
      hardware_status: string;
      runtime_status?: string;
      disk: { status: string };
    };
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
  const [workloadAccepted, setWorkloadAccepted] = useState(false);
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
          ...(plan.capability === "video"
            ? { workload_accepted: workloadAccepted }
            : {}),
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
    fit?.hardware_status === "estimated_fit" &&
    fit.disk.status === "file_fits" &&
    fit.runtime_status !== "runtime_unavailable";
  return (
    <section className="panel hub-install" aria-label="Install reviewed model">
      <h2>
        {downloadId ? "Model preparation" : "Ready to review and install"}
      </h2>
      <p className="muted">
        {plan.capability === "embedding"
          ? "AI Station downloads the encoder and its fixed tokenizer, checks the complete graph and probes it on CPU. Use for memory is a separate choice; installation keeps your current encoder."
          : plan.capability === "speech"
            ? "AI Station prepares the fixed local speech engine and companions, then verifies your checkpoint before adding it to Audio and compatible assistant tools."
            : plan.capability === "video"
              ? "AI Station prepares the fixed local video engine and companions, then verifies your checkpoint before adding it to Video and compatible assistant tools."
              : plan.capability === "image"
                ? "AI Station prepares the required image engine and companions, then verifies your checkpoint before adding it to Images and compatible assistant tools."
                : "AI Station checks the download and fits the model to your GPUs before adding it to Chat. Open a conversation when preparation is complete."}
      </p>
      {!!plan.component_licenses?.length && (
        <details className="hub-context-options">
          <summary>Required engine, components and licenses</summary>
          <ul>
            {plan.components?.map((file) => (
              <li key={file.role}>
                {file.filename} · {(file.size_bytes / 1024 ** 3).toFixed(2)} GiB
              </li>
            ))}
          </ul>
          <ul>
            {plan.component_licenses.map((license) => (
              <li key={license.url}>
                <a href={license.url} target="_blank" rel="noreferrer">
                  {license.name} ↗
                </a>
              </li>
            ))}
          </ul>
          <p className="muted">
            Existing verified objects are reused. Engine setup and your new
            checkpoint appear as related Runs; Stop covers the complete
            preparation.
          </p>
        </details>
      )}
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
              and agree to download this model
              {["image", "video", "speech", "embedding"].includes(
                plan.capability ?? "",
              )
                ? " and its required licensed components"
                : ""}
              .
            </span>
          </label>
          {plan.capability === "video" && (
            <label className="hub-license">
              <input
                type="checkbox"
                checked={workloadAccepted}
                onChange={(event) => setWorkloadAccepted(event.target.checked)}
              />
              <span>
                I accept this video profile: 1280 × 704, one 12 GiB GPU and at
                least 24 GiB system RAM. It deliberately processes part of the
                model in RAM (CPU offload), with an 11 GiB application memory
                limit and no swap.
              </span>
            </label>
          )}
          <Button
            disabled={
              !canManage ||
              !accepted ||
              (plan.capability === "video" && !workloadAccepted) ||
              !allowed ||
              install.isPending
            }
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
