import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Navigate, NavLink, useParams } from "react-router-dom";
import { api } from "../api";
import { ErrorNotice, Loading, PageTitle } from "../components/common";
import { Button } from "../components/ui/button";
import ChatProviders, { type ChatProviderInfo } from "./ChatProviders";
import ChatModeSwitch, { type ChatMode } from "./ChatModeSwitch";
import Connectors from "./Connectors";
import Maintenance from "./Maintenance";
import OperatorAccess from "./OperatorAccess";
import LlamaModels from "./LlamaModels";

const sections = [
  ["general", "General"],
  ["providers", "Providers"],
  ["integrations", "Integrations"],
  ["access", "Access"],
  ["maintenance", "Maintenance"],
] as const;
type Preferences = {
  version: number;
  mode: ChatMode;
  provider: string;
  model: string;
  send_key: "enter" | "ctrl-enter";
};

export default function Settings() {
  const { section } = useParams();
  if (!sections.some(([key]) => key === section))
    return <Navigate to="/settings/general" replace />;
  return (
    <>
      <PageTitle eyebrow="AI STATION / SETTINGS" title="Settings">
        Preferences, integrations and access.{" "}
        <Link to="/system/diagnostics">Check installation</Link>
      </PageTitle>
      <nav className="settings-navigation" aria-label="Settings sections">
        {sections.map(([key, name]) => (
          <NavLink key={key} to={`/settings/${key}`}>
            {name}
          </NavLink>
        ))}
      </nav>
      <div className="settings-content">
        {section === "general" && <GeneralSettings />}
        {section === "providers" && <ChatProviders />}
        {section === "integrations" && <Connectors />}
        {section === "access" && <OperatorAccess />}
        {section === "maintenance" && <Maintenance />}
      </div>
    </>
  );
}

function GeneralSettings() {
  const cache = useQueryClient();
  const preferences = useQuery({
    queryKey: ["chat-preferences"],
    queryFn: () => api<Preferences>("/chat/preferences"),
  });
  const providers = useQuery({
    queryKey: ["chat-providers"],
    queryFn: () => api<ChatProviderInfo[]>("/chat/providers"),
  });
  const [draft, setValues] = useState<Preferences | null>(null);
  const values = draft ?? preferences.data ?? null;
  const [modelBusy, setModelBusy] = useState(false);
  const provider = useQuery({
    queryKey: ["chat-provider", values?.provider],
    queryFn: () => api<ChatProviderInfo>(`/chat/providers/${values?.provider}`),
    enabled: !!values?.provider,
  });
  const save = useMutation({
    mutationFn: () =>
      api<Preferences>("/chat/preferences", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      }),
    onSuccess: (result) => {
      cache.setQueryData(["chat-preferences"], result);
      setValues(null);
    },
  });
  const busy = save.isPending || modelBusy;
  return (
    <section className="panel settings-general">
      <div className="panel-heading">
        <h2>New conversations</h2>
      </div>
      <p className="muted">
        Model and mode apply to new conversations. The send shortcut applies to
        every chat composer.
      </p>
      <ErrorNotice
        error={
          preferences.error ?? providers.error ?? provider.error ?? save.error
        }
      />
      {preferences.isPending ? (
        <Loading />
      ) : (
        values && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (!busy) save.mutate();
            }}
          >
            <div>
              <span className="settings-label">Default mode</span>
              <ChatModeSwitch
                value={values.mode}
                disabled={busy}
                onChange={(mode) => setValues({ ...values, mode })}
              />
            </div>
            <label>
              Default provider
              <select
                disabled={busy}
                value={values.provider}
                onChange={(e) =>
                  setValues({ ...values, provider: e.target.value, model: "" })
                }
              >
                {providers.data?.map((p) => (
                  <option key={p.key} value={p.key} disabled={!p.enabled}>
                    {p.name} · {p.location}
                  </option>
                ))}
              </select>
            </label>
            <div>
              <span className="settings-label">Default model</span>
              {provider.data?.builtin ? (
                <LlamaModels
                  selectionOnly
                  compact
                  value={values.model}
                  models={provider.data.models ?? []}
                  busy={save.isPending}
                  onBusy={setModelBusy}
                  onSelect={(model) => setValues({ ...values, model })}
                />
              ) : (
                <select
                  aria-label="Default model"
                  value={values.model}
                  disabled={busy}
                  onChange={(e) =>
                    setValues({ ...values, model: e.target.value })
                  }
                >
                  <option value="">Provider default</option>
                  {[
                    ...new Set(
                      [
                        ...(provider.data?.models ?? []),
                        provider.data?.default_model,
                        values.model,
                      ].filter((name): name is string => !!name),
                    ),
                  ].map((name) => (
                    <option key={name}>{name}</option>
                  ))}
                </select>
              )}
              <Link className="settings-secondary-link" to="/models">
                Manage installed models
              </Link>
            </div>
            <label>
              Send message with
              <select
                disabled={busy}
                value={values.send_key}
                onChange={(e) =>
                  setValues({
                    ...values,
                    send_key: e.target.value as Preferences["send_key"],
                  })
                }
              >
                <option value="enter">
                  Enter · Shift+Enter for a new line
                </option>
                <option value="ctrl-enter">Ctrl/⌘+Enter</option>
              </select>
            </label>
            {provider.data?.location === "external" && (
              <p className="notice">
                External AI sends selected conversation data outside this
                workstation.
              </p>
            )}
            <div className="row">
              <Button type="submit" disabled={busy}>
                {save.isPending ? "Saving…" : "Save preferences"}
              </Button>
              {save.isSuccess &&
                JSON.stringify(values) === JSON.stringify(preferences.data) && (
                  <span role="status" className="muted">
                    Preferences saved
                  </span>
                )}
            </div>
            {save.isError && (
              <Button
                type="button"
                variant="ghost"
                onClick={() => void preferences.refetch()}
              >
                Reload saved preferences
              </Button>
            )}
          </form>
        )
      )}
    </section>
  );
}
