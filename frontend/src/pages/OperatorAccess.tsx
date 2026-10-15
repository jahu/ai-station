import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { Badge, ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";
import type { OperatorStatus } from "./OperatorLogin";
import { useListKeyboard } from "./useListKeyboard";

type NodeRow = {
  id: string;
  name: string;
  kind: string;
  transport: string;
  ownership: string;
  status?: string;
  authenticated: boolean;
  token_issued?: boolean;
  token?: string;
};

type NodesPayload = {
  items: NodeRow[];
  remote_registration: string;
  lan_exposure: string;
  summary: string;
};

const json = (method: string, body: unknown) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

function NodeCards({
  items,
  revokePending,
  onRevoke,
}: {
  items: NodeRow[];
  revokePending: boolean;
  onRevoke: (id: string) => void;
}) {
  const headingId = useId();
  const labelId = useId();
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    items,
    (node) => node.id,
  );
  return (
    <section aria-labelledby={headingId}>
      <h3 id={headingId} className="sr-only">
        Nodes
      </h3>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a node while the list is focused. Revoke stays on the
        selected row. Authenticated LAN transport stays unpublished. There is no
        inspectable node Run.
      </p>
      <div
        ref={listRef}
        className="diagnostic-list"
        aria-labelledby={labelId}
        onKeyDown={onKeyDown}
      >
        {items.map((node, i) => {
          const current = i === index;
          const shortId = node.id.slice(0, 8);
          return (
            <div key={node.id} {...itemProps(i, node.id)}>
              <div>
                <strong>{node.name}</strong>
                <p>
                  {node.kind} · {node.transport} · {node.ownership}
                  {node.status ? ` · ${node.status}` : ""}
                </p>
              </div>
              <div className="row">
                <Badge
                  status={node.authenticated ? "available" : "unavailable"}
                />
                {node.id !== "local" && node.status !== "revoked" ? (
                  <Button
                    variant="secondary"
                    tabIndex={current ? 0 : -1}
                    disabled={revokePending}
                    aria-label={`Revoke ${node.name} ${shortId}`}
                    onClick={() => onRevoke(node.id)}
                  >
                    Revoke
                  </Button>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

export default function OperatorAccess() {
  const cache = useQueryClient();
  const status = useQuery({
    queryKey: ["operator-auth"],
    queryFn: () => api<OperatorStatus>("/operator-auth"),
  });
  const nodes = useQuery({
    queryKey: ["nodes"],
    queryFn: () => api<NodesPayload>("/nodes"),
  });
  const [password, setPassword] = useState("");
  const [current, setCurrent] = useState("");
  const [issuedToken, setIssuedToken] = useState("");
  const save = useMutation({
    mutationFn: () =>
      api<OperatorStatus>(
        "/operator-auth",
        json("PUT", {
          password,
          ...(status.data?.configured ? { current_password: current } : {}),
        }),
      ),
    onSuccess: () => {
      setPassword("");
      setCurrent("");
      void cache.invalidateQueries({ queryKey: ["operator-auth"] });
      void cache.invalidateQueries({ queryKey: ["nodes"] });
    },
  });
  const clear = useMutation({
    mutationFn: () =>
      api<OperatorStatus>(
        "/operator-auth/clear",
        json("POST", { current_password: current }),
      ),
    onSuccess: () => {
      setPassword("");
      setCurrent("");
      void cache.invalidateQueries({ queryKey: ["operator-auth"] });
      void cache.invalidateQueries({ queryKey: ["nodes"] });
    },
  });
  const logout = useMutation({
    mutationFn: () =>
      api<OperatorStatus>("/operator-auth/logout", json("POST", {})),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["operator-auth"] });
    },
  });
  const invite = useMutation({
    mutationFn: (name: string) =>
      api<NodeRow>("/nodes/invitations", json("POST", { name })),
    onSuccess: (row) => {
      setIssuedToken(row.token ?? "");
      void cache.invalidateQueries({ queryKey: ["nodes"] });
    },
  });
  const revoke = useMutation({
    mutationFn: (id: string) =>
      api<NodeRow>(`/nodes/${id}/revoke`, json("POST", {})),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["nodes"] });
    },
  });
  return (
    <>
      <section className="panel mt">
        <div className="panel-heading">
          <div>
            <h2>Operator access</h2>
            <p className="muted">Password and private network access</p>
          </div>
          <div className="row">
            {status.data?.configured ? (
              <Button
                type="button"
                variant="secondary"
                disabled={logout.isPending}
                onClick={() => logout.mutate()}
              >
                {logout.isPending ? "Signing out…" : "Sign out"}
              </Button>
            ) : null}
            <Badge
              status={
                status.data?.lan_bind_allowed ? "available" : "unavailable"
              }
            />
          </div>
        </div>
        <p>
          {status.data?.reason ??
            "The UI/API stays on loopback. LAN publish is not enabled."}
        </p>
        {status.data?.access_urls?.length ? (
          <div className="mt">
            <h3>Open AI Station on another device</h3>
            <p className="muted">
              Use the same operator password on your phone or computer.
            </p>
            {status.data.access_urls.map((url) => (
              <p key={url}>
                <a href={url} className="break-all">
                  {url}
                </a>
              </p>
            ))}
          </div>
        ) : (
          <p className="muted">
            Private network access is off. Set a password first, then configure
            the workstation's private address.
          </p>
        )}
        <p className="muted">
          {status.data?.configured
            ? "Operator password stored (hash only)."
            : "No operator password set."}{" "}
          Each device has its own session. It expires after{" "}
          {Math.round((status.data?.session_idle_seconds ?? 1800) / 60)} minutes
          idle or{" "}
          {Math.round((status.data?.session_max_age_seconds ?? 43200) / 3600)}{" "}
          hours from sign-in. Changing the password signs out all other devices.
        </p>
        {status.data?.access_urls?.some((url) => url.startsWith("http://")) ? (
          <p className="muted">
            HTTP access is for your trusted home network. Use Tailscale for an
            encrypted connection away from home.
          </p>
        ) : null}
        <ErrorNotice
          error={status.error ?? save.error ?? clear.error ?? logout.error}
        />
        <form
          className="image-form mt"
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate();
          }}
        >
          {status.data?.configured ? (
            <label>
              Current password
              <input
                type="password"
                autoComplete="current-password"
                value={current}
                onChange={(event) => setCurrent(event.target.value)}
                minLength={1}
                maxLength={200}
              />
            </label>
          ) : null}
          <label>
            {status.data?.configured
              ? "Replacement password"
              : "Operator password"}
            <input
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              minLength={12}
              maxLength={200}
              required
            />
          </label>
          <div className="row">
            <Button
              type="submit"
              disabled={save.isPending || password.length < 12}
            >
              {save.isPending
                ? "Saving…"
                : status.data?.configured
                  ? "Replace password"
                  : "Store password"}
            </Button>
            {status.data?.configured &&
            status.data.password_removal_allowed !== false ? (
              <Button
                type="button"
                variant="secondary"
                disabled={clear.isPending || !current}
                onClick={() => clear.mutate()}
              >
                {clear.isPending ? "Clearing…" : "Remove password"}
              </Button>
            ) : null}
          </div>
        </form>
      </section>
      <section className="panel mt">
        <div className="panel-heading">
          <div>
            <h2>Nodes</h2>
            <p className="muted">
              Authenticated remote registration stays unpublished
            </p>
          </div>
        </div>
        <p className="muted">{nodes.data?.summary}</p>
        <ErrorNotice error={nodes.error ?? invite.error ?? revoke.error} />
        {nodes.data?.items.length ? (
          <NodeCards
            items={nodes.data.items}
            revokePending={revoke.isPending}
            onRevoke={(id) => revoke.mutate(id)}
          />
        ) : null}
        {issuedToken ? (
          <p>
            One-time invitation token (not stored in the list):{" "}
            <code>{issuedToken}</code>
          </p>
        ) : null}
        <form
          className="image-form mt"
          onSubmit={(event) => {
            event.preventDefault();
            const fields = new FormData(event.currentTarget);
            invite.mutate(String(fields.get("name") ?? "").trim());
          }}
        >
          <label>
            Remote node name
            <input name="name" required maxLength={200} />
          </label>
          <Button
            type="submit"
            disabled={invite.isPending || !status.data?.configured}
          >
            {invite.isPending ? "Issuing…" : "Issue invitation"}
          </Button>
        </form>
      </section>
    </>
  );
}
