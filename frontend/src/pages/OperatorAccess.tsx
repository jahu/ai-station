import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { Badge, ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";

type OperatorStatus = {
  configured: boolean;
  bind_host: string;
  lan_exposure: string;
  lan_bind_allowed: boolean;
  reason: string;
};

type NodeRow = {
  id: string;
  name: string;
  kind: string;
  transport: string;
  ownership: string;
  authenticated: boolean;
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
  return (
    <>
      <section className="panel mt">
        <div className="panel-heading">
          <div>
            <h2>Operator access</h2>
            <p className="muted">
              Local credential required before any future LAN listener · not a
              session login yet
            </p>
          </div>
          <Badge
            status={status.data?.lan_bind_allowed ? "available" : "unavailable"}
          />
        </div>
        <p>
          {status.data?.reason ??
            "The UI/API stays on loopback. LAN publish is not enabled."}
        </p>
        <p className="muted">
          Bind host <code>{status.data?.bind_host ?? "127.0.0.1"}</code>
          {" · "}
          LAN exposure {status.data?.lan_exposure ?? "disabled"}
          {status.data?.configured
            ? " · operator password stored (hash only)"
            : " · no operator password"}
          . This password is never returned by the API and is not used to gate
          localhost requests. Non-loopback bind is refused even after it is set,
          because authenticated LAN transport is unpublished.
        </p>
        <ErrorNotice error={status.error ?? save.error ?? clear.error} />
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
            {status.data?.configured ? (
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
        <ErrorNotice error={nodes.error} />
        <div className="diagnostic-list">
          {nodes.data?.items.map((node) => (
            <div key={node.id}>
              <div>
                <strong>{node.name}</strong>
                <p>
                  {node.kind} · {node.transport} · {node.ownership}
                </p>
              </div>
              <Badge
                status={node.authenticated ? "available" : "unavailable"}
              />
            </div>
          ))}
        </div>
      </section>
    </>
  );
}
