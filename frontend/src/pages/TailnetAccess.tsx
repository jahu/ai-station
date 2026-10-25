import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";
import { randomId } from "../lib/random-id";

type Operation = "install" | "start" | "login" | "enable" | "disable";
type AccessRun = {
  id: string;
  status: string;
  parameters?: { operation?: Operation };
  metadata?: {
    private_access_outcome?: string;
    cleanup_requires_inspection?: boolean;
  };
  error_message?: string;
};
type Access = {
  available: boolean;
  installed?: boolean;
  revision: number;
  enabled: boolean;
  origin?: string;
  approved_origin?: string;
  node_id?: string;
  node_online?: boolean;
  serving: boolean;
  state: string;
  configuration?: string;
  run?: AccessRun;
};
type Request = {
  operation: Operation;
  expected_revision: number;
  client_request_id: string;
  node_id?: string;
  origin?: string;
};
const active = new Set([
  "queued",
  "claimed",
  "preparing",
  "running",
  "cancel_requested",
]);
const json = (body: unknown) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export default function TailnetAccess({ configured }: { configured: boolean }) {
  const cache = useQueryClient();
  const [interactive, setInteractive] = useState<{
    runId: string;
    url: string;
  }>();
  const receipt = useRef<Request | null>(null);
  const status = useQuery({
    queryKey: ["private-access"],
    queryFn: () => api<Access>("/private-access"),
    enabled: configured,
    refetchInterval: configured ? 3000 : false,
  });
  const refresh = () => {
    void cache.invalidateQueries({ queryKey: ["private-access"] });
    void cache.invalidateQueries({ queryKey: ["operator-auth"] });
  };
  const action = useMutation({
    mutationFn: (operation: Operation) => {
      const value = status.data;
      if (!value) throw new Error("Refresh private access before continuing.");
      if (
        receipt.current?.operation !== operation ||
        receipt.current.expected_revision !== value.revision
      ) {
        receipt.current = {
          operation,
          expected_revision: value.revision,
          client_request_id: randomId(),
          ...(operation === "enable"
            ? { node_id: value.node_id, origin: value.origin }
            : {}),
        };
      }
      return api<AccessRun>("/private-access", json(receipt.current));
    },
    onSuccess: () => {
      setInteractive(undefined);
      refresh();
    },
  });
  const copy = useMutation({
    mutationFn: async (address: string) => {
      if (navigator.clipboard?.writeText)
        return navigator.clipboard.writeText(address);
      const input = document.createElement("textarea");
      input.value = address;
      input.style.position = "fixed";
      input.style.left = "-9999px";
      document.body.appendChild(input);
      try {
        input.select();
        if (!document.execCommand("copy"))
          throw new Error("Select and copy the private address above.");
      } finally {
        input.remove();
      }
    },
  });
  const cancel = useMutation({
    mutationFn: (id: string) => api(`/runs/${id}/cancel`, { method: "POST" }),
    onSuccess: refresh,
  });
  const link = useMutation({
    mutationFn: (id: string) =>
      api<{ url?: string }>(`/private-access/actions/${id}/link`, {
        cache: "no-store",
      }),
    onSuccess: (value, runId) => {
      if (value.url) setInteractive({ runId, url: value.url });
    },
  });
  const value = status.data;
  const run = value?.run;
  const busy = action.isPending || !!(run && active.has(run.status));
  const needsInspection = run?.metadata?.cleanup_requires_inspection;
  const connected = !!(
    value?.enabled &&
    value.serving &&
    value.node_online &&
    value.origin === value.approved_origin
  );
  const url = interactive?.runId === run?.id ? interactive?.url : undefined;
  const needConsent =
    run?.metadata?.private_access_outcome === "https_consent_required";
  const canLink = run?.parameters?.operation === "login" || needConsent;
  const label = !configured
    ? "Set a password first"
    : status.isPending
      ? "Checking…"
      : connected
        ? "Connected"
        : busy
          ? "Setting up…"
          : value?.state === "NeedsMachineAuth"
            ? "Device approval needed"
            : value?.state === "NeedsLogin"
              ? "Sign-in needed"
              : needConsent
                ? "HTTPS approval needed"
                : value?.state === "not_installed"
                  ? "Not installed"
                  : value?.node_online
                    ? "Ready to enable"
                    : value?.state === "stopped"
                      ? "Stopped"
                      : "Needs attention";

  return (
    <section
      className="panel mt operator-access-panel"
      aria-labelledby="tailnet-heading"
    >
      <div className="panel-heading">
        <div>
          <h2 id="tailnet-heading">Access from anywhere</h2>
          <p className="muted">
            A private, encrypted connection through Tailscale
          </p>
        </div>
        <span className="muted" role="status">
          {label}
        </span>
      </div>
      <div className="operator-access-body">
        <p>
          Use AI Station on your phone away from home. Connect your devices to
          the same Tailscale account, then sign in with your AI Station
          password.
        </p>
        {!configured ? (
          <p className="muted">Store your operator password above to begin.</p>
        ) : (
          <>
            <ol className="ml-5 list-decimal space-y-2 my-4">
              <li>
                Install and start the private connection on this workstation.
              </li>
              <li>Sign in to Tailscale and approve this device.</li>
              <li>
                Enable the private HTTPS address, then open it on your phone.
              </li>
            </ol>
            {value?.available && !value.installed ? (
              <p className="muted">
                Setup downloads the verified Tailscale runtime (about 40 MB) for
                AI Station.
              </p>
            ) : null}
            {value?.state === "NeedsMachineAuth" ? (
              <p>
                Approve this workstation in your Tailscale account, then return
                here.
              </p>
            ) : null}
            {needConsent ? (
              <p>
                Approve HTTPS for your Tailscale network, then choose Enable
                private access again.
              </p>
            ) : null}
            {needsInspection ? (
              <p>
                The previous operation needs inspection. Disable the connection
                before setting it up again.
              </p>
            ) : null}
            {value?.configuration === "unexpected" ? (
              <p>
                The private service has an unexpected configuration. Inspect its
                Run before continuing.
              </p>
            ) : null}
            {value?.node_online && value.origin ? (
              <p className="break-all">
                <strong>Private address:</strong> {value.origin}
              </p>
            ) : null}
            {connected && value?.origin ? (
              <div className="row mt">
                <a
                  href={value.origin}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-link"
                >
                  Open AI Station remotely
                </a>
                <Button
                  variant="secondary"
                  onClick={() => copy.mutate(value.origin!)}
                >
                  Copy address
                </Button>
              </div>
            ) : null}
            <div className="row mt">
              {value?.available && !busy && !needsInspection ? (
                <>
                  {!value.installed ? (
                    <Button onClick={() => action.mutate("install")}>
                      Install private access
                    </Button>
                  ) : value.state === "stopped" ? (
                    <Button onClick={() => action.mutate("start")}>
                      Start private connection
                    </Button>
                  ) : value.state === "NeedsLogin" ? (
                    <Button onClick={() => action.mutate("login")}>
                      Prepare Tailscale sign-in
                    </Button>
                  ) : value.node_online &&
                    !connected &&
                    value.configuration !== "unexpected" ? (
                    <Button onClick={() => action.mutate("enable")}>
                      Enable private access
                    </Button>
                  ) : null}
                </>
              ) : null}
              {run && canLink && !url ? (
                <Button
                  variant="secondary"
                  disabled={link.isPending}
                  onClick={() => link.mutate(run.id)}
                >
                  {link.isPending
                    ? "Preparing link…"
                    : needConsent
                      ? "Get HTTPS approval link"
                      : "Get Tailscale sign-in link"}
                </Button>
              ) : null}
              {url ? (
                <a
                  href={url}
                  target="_blank"
                  rel="noopener noreferrer"
                  referrerPolicy="no-referrer"
                  className="text-link"
                >
                  {needConsent
                    ? "Approve HTTPS in Tailscale"
                    : "Sign in to Tailscale"}
                </a>
              ) : null}
              {run && active.has(run.status) ? (
                <Button
                  variant="secondary"
                  disabled={
                    cancel.isPending || run.status === "cancel_requested"
                  }
                  onClick={() => cancel.mutate(run.id)}
                >
                  {run.status === "cancel_requested"
                    ? "Stopping…"
                    : "Stop setup"}
                </Button>
              ) : null}
              {value?.available &&
              !busy &&
              (value.installed || needsInspection) ? (
                <Button
                  variant="secondary"
                  onClick={() => action.mutate("disable")}
                >
                  Disable private connection
                </Button>
              ) : null}
              <Button
                variant="secondary"
                disabled={status.isFetching}
                onClick={refresh}
              >
                Refresh connection
              </Button>
              {run ? (
                <a href={`#/runs/${run.id}`} className="text-link">
                  Inspect setup Run
                </a>
              ) : null}
            </div>
            {link.isSuccess && !link.data?.url && !url ? (
              <p className="muted">
                No active sign-in link. Refresh the connection or prepare a new
                sign-in.
              </p>
            ) : null}
            {run?.error_message ? (
              <p role="alert">{run.error_message}</p>
            ) : null}
            {value?.available === false ? (
              <p className="muted">
                The private-access service is unavailable. Check the Host Runner
                in System.
              </p>
            ) : null}
            <ErrorNotice
              error={
                status.error ??
                action.error ??
                cancel.error ??
                link.error ??
                copy.error
              }
            />
            <p className="muted mt">
              Your home-network address keeps working. Install Tailscale on your
              phone and sign in to the same account to use the private address.
            </p>
          </>
        )}
      </div>
    </section>
  );
}
