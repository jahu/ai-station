import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorNotice, Loading, PageTitle } from "../components/common";
import { Button } from "../components/ui/button";

export type OperatorStatus = {
  configured: boolean;
  session_required?: boolean;
  authenticated?: boolean;
  session_scope?: string;
  session_idle_seconds?: number;
  session_max_age_seconds?: number;
  session_cookie?: {
    httponly: boolean;
    samesite: string;
    secure: boolean;
    path: string;
  };
  issued_at?: string | null;
  last_seen_at?: string | null;
  expires_at?: string | null;
  idle_expires_at?: string | null;
  bind_host: string;
  lan_exposure: string;
  lan_bind_allowed: boolean;
  reason: string;
  access_urls?: string[];
  password_removal_allowed?: boolean;
};

const json = (method: string, body: unknown) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

function LoginForm() {
  const cache = useQueryClient();
  const [password, setPassword] = useState("");
  const login = useMutation({
    mutationFn: () =>
      api<OperatorStatus>("/operator-auth/login", json("POST", { password })),
    onSuccess: () => {
      setPassword("");
      void cache.invalidateQueries({ queryKey: ["operator-auth"] });
    },
  });
  return (
    <main id="main" tabIndex={-1} className="workspace">
      <PageTitle eyebrow="YOUR AI WORKSTATION" title="Unlock this workstation.">
        Enter your operator password to continue. Your conversations, agents and
        artifacts are available after sign-in. Sessions expire after 30 minutes
        idle or 12 hours from sign-in.
      </PageTitle>
      <section className="panel">
        <ErrorNotice error={login.error} />
        <form
          className="image-form"
          onSubmit={(event) => {
            event.preventDefault();
            login.mutate();
          }}
        >
          <label>
            Operator password
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              minLength={1}
              maxLength={200}
              required
            />
          </label>
          <Button
            type="submit"
            disabled={login.isPending || password.length < 1}
          >
            {login.isPending ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </section>
    </main>
  );
}

export default function OperatorGate({ children }: { children: ReactNode }) {
  const status = useQuery({
    queryKey: ["operator-auth"],
    queryFn: () => api<OperatorStatus>("/operator-auth"),
  });
  if (status.isPending) {
    return <Loading />;
  }
  if (status.error) {
    return (
      <main id="main" tabIndex={-1} className="workspace">
        <ErrorNotice error={status.error} />
      </main>
    );
  }
  if (status.data?.session_required && !status.data.authenticated) {
    return <LoginForm />;
  }
  return children;
}
