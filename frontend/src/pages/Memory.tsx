import { useId, useState, type KeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { Pin, Plus, Search } from "lucide-react";
import { api } from "../api";
import { Empty, ErrorNotice, Loading, PageTitle } from "../components/common";
import { Button } from "../components/ui/button";
import { useListKeyboard } from "./useListKeyboard";

type Scope = "global" | "project" | "conversation" | "agent";
interface Entry {
  id: string;
  scope: Scope;
  scope_id: string;
  memory_type: string;
  content: string;
  tags: string[];
  confidence: number | null;
  pinned: boolean;
  enabled: boolean;
  updated_at: string;
  created_at: string;
  source_run_id: string | null;
  source_conversation_id: string | null;
  source_message_id: string | null;
}
const kinds = [
  "fact",
  "decision",
  "preference",
  "project_context",
  "summary",
  "observation",
  "procedure",
];
const json = (method: string, body: unknown) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

interface EmbeddingSetup {
  configured: boolean;
  endpoint: string;
  model: string;
  dimension: number | null;
  indexed_count: number;
  memory_count: number;
  last_health_run_id: string | null;
  last_index_run_id: string | null;
}

function EmbeddingsPanel() {
  const cache = useQueryClient();
  const [endpoint, setEndpoint] = useState("");
  const [model, setModel] = useState("");
  const [semantic, setSemantic] = useState("");
  const setup = useQuery({
    queryKey: ["memory-embeddings"],
    queryFn: () => api<EmbeddingSetup>("/memory/embeddings/setup"),
  });
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<EmbeddingSetup>("/memory/embeddings/setup", json("PUT", body)),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["memory-embeddings"] });
    },
  });
  const start = useMutation({
    mutationFn: (path: string) =>
      api<{ id: string }>(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: path.endsWith("/search")
          ? JSON.stringify({ query: semantic })
          : "{}",
      }),
  });
  const current = setup.data;
  return (
    <section className="panel">
      <h2>Optional embeddings</h2>
      <p className="muted">
        Semantic search stays off until you point AI Station at a local
        OpenAI-compatible embeddings endpoint that already has its model
        installed. Weights are never downloaded. Empty or all-zero vectors are
        rejected. Full-text search above does not need this.
      </p>
      {current?.configured ? (
        <p className="muted">
          Using {current.model} at {current.endpoint}
          {current.dimension ? ` · ${current.dimension}-dimension probe` : ""}
          {` · ${current.indexed_count} indexed / ${current.memory_count} memories`}
        </p>
      ) : (
        <p className="notice">Embeddings are not configured.</p>
      )}
      <label>
        Local embeddings base URL
        <input
          value={endpoint}
          onChange={(event) => setEndpoint(event.target.value)}
          placeholder="http://127.0.0.1:11434/v1"
        />
      </label>
      <label>
        Model name already served by that endpoint
        <input
          value={model}
          onChange={(event) => setModel(event.target.value)}
          placeholder="nomic-embed-text"
        />
      </label>
      <div className="row">
        <Button
          disabled={save.isPending || !endpoint || !model}
          onClick={() => save.mutate({ endpoint, model })}
        >
          Save local setup
        </Button>
        <Button
          variant="secondary"
          disabled={!current?.configured || start.isPending}
          onClick={() => start.mutate("/memory/embeddings/health")}
        >
          Check endpoint
        </Button>
        <Button
          variant="secondary"
          disabled={!current?.configured || start.isPending}
          onClick={() => start.mutate("/memory/embeddings/index")}
        >
          Index memories
        </Button>
        {current?.configured && (
          <Button
            variant="secondary"
            disabled={save.isPending}
            onClick={() =>
              save.mutate({ clear: true, endpoint: "", model: "" })
            }
          >
            Clear setup
          </Button>
        )}
      </div>
      <label>
        Semantic query
        <input
          value={semantic}
          onChange={(event) => setSemantic(event.target.value)}
          placeholder="Requires a configured endpoint"
          disabled={!current?.configured}
        />
      </label>
      <Button
        variant="secondary"
        disabled={!current?.configured || !semantic || start.isPending}
        onClick={() => start.mutate("/memory/embeddings/search")}
      >
        Semantic search
      </Button>
      <ErrorNotice error={setup.error ?? save.error ?? start.error} />
      {start.data?.id && (
        <p>
          <Link to={`/runs/${start.data.id}`}>Inspect embeddings Run →</Link>
        </p>
      )}
      {current?.last_health_run_id && (
        <p className="muted">
          <Link to={`/runs/${current.last_health_run_id}`}>
            Last health Run
          </Link>
          {current.last_index_run_id && (
            <>
              {" · "}
              <Link to={`/runs/${current.last_index_run_id}`}>
                Last index Run
              </Link>
            </>
          )}
        </p>
      )}
    </section>
  );
}

function MemoryCards({ entries }: { entries: Entry[] }) {
  const headingId = useId();
  const labelId = useId();
  const { listRef, onKeyDown, itemProps } = useListKeyboard(
    entries,
    (entry) => entry.id,
  );
  return (
    <section aria-labelledby={headingId}>
      <h2 id={headingId} className="sr-only">
        Memory
      </h2>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a memory while the list is focused. Enter inspects it.
      </p>
      <div
        ref={listRef}
        className="memory-grid"
        aria-labelledby={labelId}
        onKeyDown={onKeyDown}
      >
        {entries.map((entry, i) => {
          return (
            <Link
              className="panel memory-card"
              to={`/memory/${entry.id}`}
              key={entry.id}
              aria-label={`Inspect ${entry.memory_type.replaceAll("_", " ")} ${entry.id.slice(0, 8)}`}
              {...itemProps(i, entry.id)}
            >
              <div className="row">
                <span className="tiny-tag">{entry.scope}</span>
                <span className="muted">
                  {entry.memory_type.replaceAll("_", " ")}
                </span>
                {entry.pinned && <Pin size={15} aria-hidden="true" />}
                {!entry.enabled && <span className="tiny-tag">Disabled</span>}
              </div>
              <p>{entry.content}</p>
              <div className="row muted">
                {entry.tags.map((tag) => (
                  <span key={tag}>#{tag}</span>
                ))}
              </div>
              <small className="muted">
                {entry.source_run_id ||
                entry.source_message_id ||
                entry.source_conversation_id
                  ? "Linked source"
                  : "User entered"}{" "}
                · {new Date(entry.updated_at).toLocaleString()}
              </small>
            </Link>
          );
        })}
      </div>
    </section>
  );
}

export function Memory() {
  const [searchParams] = useSearchParams();
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState(searchParams.get("scope") ?? "");
  const [target, setTarget] = useState(searchParams.get("scope_id") ?? "");
  const [disabled, setDisabled] = useState(false);
  const [offset, setOffset] = useState(0);
  const params = new URLSearchParams({
    q: query,
    include_disabled: String(disabled),
    limit: "50",
    offset: String(offset),
  });
  if (scope) params.set("scope", scope);
  if (target) params.set("scope_id", target);
  const entries = useQuery({
    queryKey: ["memory", params.toString()],
    queryFn: () => api<Entry[]>(`/memory?${params}`),
  });
  return (
    <>
      <PageTitle
        eyebrow="CONTEXT / LOCAL MEMORY"
        title="Memory"
        action={
          <Link className="button" to="/memory/new">
            <Plus size={16} /> Add memory
          </Link>
        }
      >
        Inspect what AI Station remembers, where it came from, and where it
        applies.
      </PageTitle>
      <EmbeddingsPanel />
      <section className="panel memory-filters">
        <label>
          <Search size={15} /> Search memory
          <input
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setOffset(0);
            }}
            placeholder="Search content and tags…"
            maxLength={500}
          />
        </label>
        <label>
          Scope
          <select
            value={scope}
            onChange={(e) => {
              setScope(e.target.value);
              setTarget("");
              setOffset(0);
            }}
          >
            <option value="">All scopes</option>
            {["global", "project", "conversation", "agent"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        {scope && scope !== "global" && (
          <label>
            Scope ID
            <input
              value={target}
              onChange={(e) => {
                setTarget(e.target.value);
                setOffset(0);
              }}
              placeholder={`${scope} UUID`}
            />
          </label>
        )}
        <label className="memory-check">
          <input
            type="checkbox"
            checked={disabled}
            onChange={(e) => {
              setDisabled(e.target.checked);
              setOffset(0);
            }}
          />{" "}
          Include disabled
        </label>
      </section>
      <ErrorNotice error={entries.error} />
      {entries.isPending ? (
        <Loading />
      ) : entries.data?.length === 0 ? (
        <section className="panel">
          <Empty title="No matching memories">
            Add an entry or adjust your filters. Nothing is remembered
            invisibly.
          </Empty>
        </section>
      ) : (
        <MemoryCards entries={entries.data ?? []} />
      )}
      <div className="row">
        <Button
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - 50))}
        >
          Previous
        </Button>
        <span className="muted">Page {offset / 50 + 1}</span>
        <Button
          disabled={entries.data?.length !== 50}
          onClick={() => setOffset(offset + 50)}
        >
          Next
        </Button>
      </div>
    </>
  );
}

export function MemoryDetail() {
  const { id } = useParams();
  const entry = useQuery({
    queryKey: ["memory-entry", id],
    queryFn: () => api<Entry>(`/memory/${id}`),
    enabled: Boolean(id),
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  if (id && entry.isPending) return <Loading />;
  if (entry.error) return <ErrorNotice error={entry.error} />;
  return <MemoryEditor key={id ?? "new"} entry={entry.data} />;
}

function MemoryFlagChoiceList({
  pinned,
  enabled,
  showEnabled,
  onPinned,
  onEnabled,
}: {
  pinned: boolean;
  enabled: boolean;
  showEnabled: boolean;
  onPinned: (value: boolean) => void;
  onEnabled: (value: boolean) => void;
}) {
  const labelId = useId();
  const items = [
    { key: "pinned" as const, title: "Pinned context", checked: pinned },
    ...(showEnabled
      ? [{ key: "enabled" as const, title: "Enabled", checked: enabled }]
      : []),
  ];
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    items,
    (item) => item.key,
  );
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown(event);
    if (event.defaultPrevented) return;
    if (event.key !== " " && event.key !== "Enter") return;
    const target = event.target as HTMLElement;
    if (target.closest("a, button, textarea, input, summary, select")) return;
    const item = items[index];
    if (!item) return;
    event.preventDefault();
    if (item.key === "pinned") onPinned(!pinned);
    else onEnabled(!enabled);
  };
  return (
    <div className="agent-wide">
      <p id={labelId} className="dashboard-note">
        Arrow keys choose pin or enabled while the list is focused. Space or
        Enter selects it. Disabled or unpinned entries leave historical Chat
        snapshots unchanged. There is no inspectable memory-flag Run.
      </p>
      <div
        ref={listRef}
        className="memory-choice-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {items.map((item, i) => {
          const current = i === index;
          return (
            <div
              key={item.key}
              aria-label={`Memory ${item.key}`}
              {...itemProps(i, item.key)}
            >
              <label className="memory-check">
                <input
                  type="checkbox"
                  checked={item.checked}
                  tabIndex={current ? 0 : -1}
                  onChange={(event) =>
                    item.key === "pinned"
                      ? onPinned(event.target.checked)
                      : onEnabled(event.target.checked)
                  }
                />
                {item.title}
              </label>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function MemoryEditor({ entry }: { entry?: Entry }) {
  const cache = useQueryClient();
  const navigate = useNavigate();
  const [scope, setScope] = useState<Scope>(entry?.scope ?? "global");
  const [scopeId, setScopeId] = useState(entry?.scope_id ?? "");
  const [content, setContent] = useState(entry?.content ?? "");
  const [kind, setKind] = useState(entry?.memory_type ?? "fact");
  const [tags, setTags] = useState(entry?.tags.join(", ") ?? "");
  const [pinned, setPinned] = useState(entry?.pinned ?? false);
  const [enabled, setEnabled] = useState(entry?.enabled ?? true);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [version, setVersion] = useState(entry?.updated_at);
  const targets = useQuery({
    queryKey: ["memory-targets", scope],
    enabled: !entry && scope !== "global",
    queryFn: () =>
      api<{ id: string; name?: string; title?: string }[]>(
        scope === "project"
          ? "/projects?limit=500"
          : scope === "agent"
            ? "/agents?limit=200"
            : "/chat/conversations",
      ),
  });
  const save = useMutation({
    mutationFn: () =>
      api<Entry>(
        entry ? `/memory/${entry.id}` : "/memory",
        json(entry ? "PUT" : "POST", {
          content,
          memory_type: kind,
          tags: [
            ...new Set(
              tags
                .split(",")
                .map((t) => t.trim())
                .filter(Boolean),
            ),
          ],
          pinned,
          confidence: entry?.confidence ?? null,
          ...(entry
            ? { enabled, expected_updated_at: version }
            : { scope, scope_id: scope === "global" ? null : scopeId }),
        }),
      ),
    onSuccess: (data) => {
      setVersion(data.updated_at);
      cache.setQueryData(["memory-entry", data.id], data);
      void cache.invalidateQueries({ queryKey: ["memory"] });
      if (!entry) navigate(`/memory/${data.id}`);
    },
  });
  const remove = useMutation({
    mutationFn: () =>
      api<void>(
        `/memory/${entry!.id}`,
        json("DELETE", { expected_updated_at: version }),
      ),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["memory"] });
      navigate("/memory");
    },
  });
  return (
    <>
      <PageTitle
        eyebrow="CONTEXT / INSPECTABLE MEMORY"
        title={entry ? "Memory entry" : "Add memory"}
        action={<Link to="/memory">All memories</Link>}
      >
        Only enabled, pinned global and conversation entries are included in new
        Chat Runs. Agents can explicitly retrieve their own enabled scoped
        memories.
      </PageTitle>
      <ErrorNotice error={save.error ?? remove.error} />
      <form
        className="panel memory-editor"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <div className="memory-filters">
          <label>
            Scope
            <select
              disabled={Boolean(entry)}
              value={scope}
              onChange={(e) => {
                setScope(e.target.value as Scope);
                setScopeId("");
              }}
            >
              {["global", "project", "conversation", "agent"].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
          {scope !== "global" && (
            <label>
              Scope target
              {entry ? (
                <input
                  required
                  readOnly={Boolean(entry)}
                  value={scopeId}
                  onChange={(e) => setScopeId(e.target.value)}
                  placeholder="Existing scope UUID"
                />
              ) : (
                <select
                  required
                  value={scopeId}
                  onChange={(e) => setScopeId(e.target.value)}
                >
                  <option value="">Select {scope}…</option>
                  {targets.data?.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name ?? t.title} · {t.id.slice(0, 8)}
                    </option>
                  ))}
                </select>
              )}
            </label>
          )}
          <label>
            Type
            <select value={kind} onChange={(e) => setKind(e.target.value)}>
              {kinds.map((k) => (
                <option key={k}>{k}</option>
              ))}
            </select>
          </label>
        </div>
        <ErrorNotice error={targets.error} />
        <label>
          Content
          <textarea
            required
            rows={9}
            maxLength={16000}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="A preference, decision, observation, or procedure worth keeping…"
          />
        </label>
        <label>
          Tags
          <input
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            placeholder="Comma-separated tags"
          />
        </label>
        <MemoryFlagChoiceList
          pinned={pinned}
          enabled={enabled}
          showEnabled={Boolean(entry)}
          onPinned={setPinned}
          onEnabled={setEnabled}
        />
        <Button type="submit" disabled={save.isPending || remove.isPending}>
          {save.isPending ? "Saving…" : "Save memory"}
        </Button>
      </form>
      {entry && (
        <section className="panel memory-editor">
          <h2>Provenance</h2>
          <p>
            {entry.source_run_id ||
            entry.source_message_id ||
            entry.source_conversation_id
              ? "User-recorded memory linked to the following source. The link does not certify the claim."
              : "User-entered memory. No AI-generated source is claimed."}
          </p>
          <p className="muted">
            Created {new Date(entry.created_at).toLocaleString()} · Updated{" "}
            {new Date(version!).toLocaleString()}
          </p>
          {entry.source_run_id && (
            <Link to={`/runs/${entry.source_run_id}`}>
              Source Run {entry.source_run_id}
            </Link>
          )}
          {entry.source_conversation_id && (
            <Link to={`/chat/${entry.source_conversation_id}`}>
              Source conversation
            </Link>
          )}
          {entry.source_message_id && (
            <code>Message {entry.source_message_id}</code>
          )}
          {entry.scope === "project" && (
            <Link to={`/projects/${entry.scope_id}`}>Scoped project</Link>
          )}
          {entry.scope === "conversation" && (
            <Link to={`/chat/${entry.scope_id}`}>Scoped conversation</Link>
          )}
          <p className="muted">
            Deleting removes this entry and its search index. Existing Run
            context snapshots remain in audit history.
          </p>
          {confirmDelete ? (
            <div className="row">
              <Button
                disabled={remove.isPending || save.isPending}
                onClick={() => remove.mutate()}
              >
                Permanently delete memory
              </Button>
              <Button onClick={() => setConfirmDelete(false)}>
                Keep memory
              </Button>
            </div>
          ) : (
            <Button onClick={() => setConfirmDelete(true)}>
              Delete memory…
            </Button>
          )}
        </section>
      )}
    </>
  );
}
