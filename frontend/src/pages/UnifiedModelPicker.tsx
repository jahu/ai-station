import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronDown, Cloud, Cpu, Search, X } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { ErrorNotice, Loading } from "../components/common";
import { useListKeyboard } from "./useListKeyboard";

export type CatalogModel = {
  model_ref: string;
  provider_key: string;
  provider_name: string;
  model_key: string;
  display_name: string;
  location: "local" | "external";
  runtime_kind: "llama.cpp" | "local-server" | "external";
  availability: string;
  unavailable_reason: string;
  config_version: string;
  endpoint_host: string;
  modalities: string[];
  file_size_bytes?: number | null;
  quantization?: string;
};
export type Catalog = {
  models: CatalogModel[];
  providers: {
    key: string;
    name: string;
    location: string;
    enabled: boolean;
    discovered: boolean;
    error: string;
  }[];
};
const states: Record<string, string> = {
  ready: "Ready",
  available: "Available",
  configured: "Configured",
  loads_when_needed: "Loads when needed",
  loading: "Loading",
  needs_inspection: "Needs inspection",
  unavailable: "Unavailable",
};
function displayName(value: string) {
  const parts = value.replace(/\.gguf$/i, "").split(" · ");
  return parts.length === 2 &&
    parts[1].toLowerCase().startsWith(parts[0].toLowerCase())
    ? parts[1]
    : parts.join(" · ");
}

export default function UnifiedModelPicker({
  providerKey,
  modelKey,
  label,
  location,
  busy,
  onSelect,
}: {
  providerKey: string;
  modelKey: string;
  label?: string;
  busy?: boolean;
  onSelect: (choice: CatalogModel) => void;
  location?: "local" | "external";
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [discovery, setDiscovery] = useState("");
  const catalog = useQuery({
    queryKey: ["chat-model-catalog"],
    queryFn: () => api<Catalog>("/chat/model-catalog"),
    staleTime: 30000,
  });
  const discovered = useQuery({
    queryKey: ["chat-model-catalog-discovery", discovery],
    queryFn: () =>
      api<Catalog>(
        "/chat/model-catalog?discover_provider=" +
          encodeURIComponent(discovery),
      ),
    enabled: open && !!discovery,
    staleTime: 30000,
  });
  const data = discovered.data ?? catalog.data;
  const models = data?.models ?? [];
  const selected = models.find(
    (item) => item.provider_key === providerKey && item.model_key === modelKey,
  );
  const query = search.trim().toLowerCase();
  const filtered = models.filter((item) =>
    `${item.display_name} ${item.provider_name} ${item.runtime_kind}`
      .toLowerCase()
      .includes(query),
  );
  const selectable = filtered.filter(
    (item) => !["unavailable", "needs_inspection"].includes(item.availability),
  );
  const { listRef, onKeyDown, itemProps } = useListKeyboard(
    selectable,
    (item) => item.model_ref,
    { initialKey: selected?.model_ref },
  );
  const provider = data?.providers?.find((item) => item.key === providerKey);
  const external =
    (selected?.location ?? provider?.location ?? location) === "external";
  return (
    <div className="model-picker model-picker-compact">
      <Dialog.Root
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (next) {
            setSearch("");
            setDiscovery("");
            void catalog.refetch();
          }
        }}
      >
        <Dialog.Trigger asChild>
          <button
            type="button"
            className="model-picker-trigger"
            aria-label="Change model"
            disabled={busy}
          >
            {external ? <Cloud size={18} /> : <Cpu size={18} />}
            <span>
              <strong>
                {(selected ? displayName(selected.display_name) : undefined) ||
                  label ||
                  (modelKey.startsWith("llamacpp:")
                    ? "Local model"
                    : modelKey) ||
                  "Choose a model"}
              </strong>
              <small>
                {modelKey.startsWith("llamacpp:")
                  ? "llama.cpp · local GGUF"
                  : external
                    ? `External · ${selected?.provider_name ?? provider?.name ?? providerKey}`
                    : "Local server"}
              </small>
            </span>
            <ChevronDown size={16} />
          </button>
        </Dialog.Trigger>
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content className="model-dialog unified-model-dialog">
            <div className="model-dialog-heading">
              <div>
                <Dialog.Title>Choose a model</Dialog.Title>
                <Dialog.Description>
                  Local models and configured providers. Selecting a model
                  starts no workload.
                </Dialog.Description>
              </div>
              <Dialog.Close
                className="icon-button"
                aria-label="Close model picker"
              >
                <X size={20} />
              </Dialog.Close>
            </div>
            <label className="model-search">
              <Search size={17} />
              <span className="sr-only">Search models</span>
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search models or providers…"
              />
            </label>
            <ErrorNotice error={catalog.error ?? discovered.error} />
            {catalog.isPending && <Loading />}
            <div
              ref={listRef}
              onKeyDown={onKeyDown}
              className="unified-model-options"
              aria-label="Model choices"
            >
              {(["llama.cpp", "local-server", "external"] as const).map(
                (kind) => {
                  const entries = filtered.filter(
                    (item) => item.runtime_kind === kind,
                  );
                  const providers =
                    data?.providers?.filter((provider) =>
                      kind === "external"
                        ? provider.location === "external"
                        : kind === "local-server" &&
                          provider.location === "local",
                    ) ?? [];
                  if (!entries.length && !providers.length) return null;
                  return (
                    <section
                      key={kind}
                      aria-label={
                        kind === "llama.cpp"
                          ? "Local llama.cpp models"
                          : kind === "local-server"
                            ? "Local servers"
                            : "External providers"
                      }
                    >
                      <h3>
                        {kind === "llama.cpp"
                          ? "Local · llama.cpp"
                          : kind === "local-server"
                            ? "Local servers"
                            : "External"}
                      </h3>
                      {entries.map((item) => {
                        const index = selectable.findIndex(
                          (candidate) => candidate.model_ref === item.model_ref,
                        );
                        const active =
                          item.provider_key === providerKey &&
                          item.model_key === modelKey;
                        return (
                          <button
                            type="button"
                            key={item.model_ref}
                            className="model-option"
                            aria-pressed={active}
                            data-model-ref={item.model_ref}
                            disabled={busy || index < 0}
                            {...(index < 0
                              ? { tabIndex: -1 }
                              : itemProps(index, item.model_ref))}
                            onClick={() => {
                              onSelect(item);
                              setOpen(false);
                            }}
                          >
                            {item.location === "external" ? (
                              <Cloud size={18} />
                            ) : (
                              <Cpu size={18} />
                            )}
                            <span className="unified-model-name">
                              <strong>{displayName(item.display_name)}</strong>
                              <small>
                                {item.unavailable_reason ||
                                  `${item.provider_name}${item.quantization ? " · " + item.quantization : ""}${item.file_size_bytes ? " · " + (item.file_size_bytes / 1024 ** 3).toFixed(1) + " GiB" : ""}${item.endpoint_host ? " · " + item.endpoint_host : ""}`}
                              </small>
                            </span>
                            <span className="chip">
                              {states[item.availability] ?? item.availability}
                            </span>
                            {active && <Check size={16} />}
                          </button>
                        );
                      })}
                      {providers.map((provider) => (
                        <div
                          className="model-provider-browse"
                          key={provider.key}
                        >
                          <button
                            type="button"
                            className="text-link"
                            disabled={
                              !provider.enabled || discovered.isFetching || busy
                            }
                            onClick={() => setDiscovery(provider.key)}
                          >
                            {discovered.isFetching && discovery === provider.key
                              ? "Checking models…"
                              : `Browse ${provider.name} models`}
                          </button>
                          {provider.error && (
                            <small className="muted">{provider.error}</small>
                          )}
                        </div>
                      ))}
                    </section>
                  );
                },
              )}
              {!filtered.length && !catalog.isPending && (
                <p className="muted">
                  No matching models. Try another name or configure a provider.
                </p>
              )}
            </div>
            <div className="model-picker-links">
              <Link to="/models">Manage local models</Link>
              <Link to="/settings/providers">Configure providers</Link>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}
