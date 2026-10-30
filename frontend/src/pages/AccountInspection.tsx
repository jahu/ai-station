import { useEffect, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  Download,
  Eye,
  File,
  Folder,
  GitBranch,
  ListChecks,
  LockKeyhole,
  MessageSquare,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Workflow,
  X,
} from "lucide-react";
import { api } from "../api";
import { useAccount, type AccountUser } from "../account-context";
import { Button } from "../components/ui/button";
import { Empty, ErrorNotice, Loading } from "../components/common";

const sections = [
  ["conversations", "Conversations", MessageSquare],
  ["artifacts", "Library", Folder],
  ["runs", "Runs", Workflow],
  ["tasks", "Tasks", ListChecks],
  ["memory", "Memory", Sparkles],
  ["agents", "Agents", Eye],
  ["projects", "Projects", GitBranch],
  ["approvals", "Approvals", ShieldCheck],
  ["providers", "Model providers", Settings2],
  ["connectors", "Connections", Settings2],
  ["creative", "Creative workspaces", Sparkles],
] as const;
type Category = (typeof sections)[number][0];
type RecordData = Record<string, unknown>;
type Row = {
  id: string;
  title: string;
  status: string | null;
  created_at: string;
};
type Page<T> = { items: T[]; total: number; offset: number; limit: number };
type Overview = {
  user: AccountUser;
  read_only: boolean;
  counts: Record<Category, number>;
  preferences: RecordData;
};
const date = (value: unknown) =>
  typeof value === "string" && !Number.isNaN(Date.parse(value))
    ? new Date(value).toLocaleString()
    : "";
const label = (value: string) => value.replaceAll("_", " ");
const text = (value: unknown) => (typeof value === "string" ? value : "");

function Pager({
  page,
  offset,
  onChange,
  name,
}: {
  page?: Page<unknown>;
  offset: number;
  onChange: (offset: number) => void;
  name: string;
}) {
  if (!page || page.total === 0) return null;
  return (
    <div className="account-inspection-pager" aria-label={`${name} pages`}>
      <span>
        {offset + 1}–{Math.min(offset + page.items.length, page.total)} of{" "}
        {page.total}
      </span>
      <Button
        variant="ghost"
        aria-label={`Previous ${name}`}
        disabled={offset === 0}
        onClick={() => onChange(Math.max(0, offset - page.limit))}
      >
        <ChevronLeft size={16} />
      </Button>
      <Button
        variant="ghost"
        aria-label={`Next ${name}`}
        disabled={offset + page.limit >= page.total}
        onClick={() => onChange(offset + page.limit)}
      >
        <ChevronRight size={16} />
      </Button>
    </div>
  );
}

function Detail({
  category,
  id,
  base,
  queryKey,
}: {
  category: Category;
  id: string;
  base: string;
  queryKey: string[];
}) {
  const [offset, setOffset] = useState(0);
  const record = useQuery({
    queryKey: [...queryKey, "record", category, id],
    queryFn: ({ signal }) =>
      api<RecordData>(`${base}/${category}/${id}`, { signal }),
  });
  const hasEntries = category === "conversations" || category === "runs";
  const entries = useQuery({
    queryKey: [...queryKey, "entries", category, id, offset],
    queryFn: ({ signal }) =>
      api<Page<RecordData>>(
        `${base}/${category}/${id}/entries?offset=${offset}`,
        { signal },
      ),
    enabled: hasEntries && !!record.data,
  });
  if (record.isPending) return <Loading />;
  if (record.error) return <ErrorNotice error={record.error} />;
  const data = record.data;
  const title =
    text(data.title) ||
    text(data.name) ||
    text(data.original_filename) ||
    text(data.action) ||
    text(data.capability) ||
    "Record details";
  const internalFile = Boolean(
    (data.metadata as RecordData | undefined)?.internal_data_output,
  );
  const media =
    category === "artifacts" &&
    !data.purged_at &&
    !data.purge_run_id &&
    !internalFile;
  const file = `/api${base}/artifacts/${id}/file`;
  const mime = text(data.mime_type);
  const bodyKeys = [
    "content",
    "prompt",
    "goal",
    "description",
    "summary",
    "system_prompt",
    "error_message",
  ];
  const metadata = Object.fromEntries(
    Object.entries(data).filter(([key]) => !bodyKeys.includes(key)),
  );
  return (
    <article
      className="account-inspection-record"
      aria-label="Inspected record"
    >
      <div className="account-inspection-record-heading">
        <h3>{title}</h3>
        <span className="muted">
          {date(data.created_at || data.requested_at)}
        </span>
      </div>
      {category === "artifacts" && (
        <>
          {internalFile && (
            <p className="notice">
              Internal intermediate file. Inspect the verified output instead.
            </p>
          )}
          {data.purged_at ? (
            <p className="notice">
              Permanently deleted. History remains; the file is unavailable.
            </p>
          ) : data.purge_run_id ? (
            <p className="notice">Permanent deletion is in progress.</p>
          ) : null}
          {!!data.trashed_at && !data.purged_at && (
            <p className="muted">This file is in Trash.</p>
          )}
          {media && (
            <div className="account-inspection-media">
              {["image/png", "image/jpeg", "image/webp"].includes(mime) ? (
                <img src={file} alt={title} />
              ) : mime === "video/mp4" ? (
                <video src={file} controls preload="metadata" />
              ) : mime === "audio/wav" ? (
                <audio src={file} controls preload="metadata" />
              ) : (
                <File size={38} />
              )}
              <Button asChild variant="secondary">
                <a href={file} target="_blank" rel="noreferrer">
                  <Download size={16} /> Open file
                </a>
              </Button>
            </div>
          )}
        </>
      )}
      {bodyKeys.map((key) =>
        text(data[key]) ? (
          <section className="account-inspection-text" key={key}>
            <h4>{label(key)}</h4>
            <p>{text(data[key])}</p>
          </section>
        ) : null,
      )}
      {hasEntries && (
        <section
          className="account-inspection-entries"
          aria-label={
            category === "conversations"
              ? "Conversation transcript"
              : "Run events"
          }
        >
          <h4>
            {category === "conversations" ? "Conversation" : "Event timeline"}
          </h4>
          <ErrorNotice error={entries.error} />
          {entries.isPending ? (
            <Loading />
          ) : entries.data?.items.length === 0 ? (
            <p className="muted">No entries recorded.</p>
          ) : (
            entries.data?.items.map((entry) => (
              <div
                className={`account-inspection-entry ${text(entry.role)}`}
                key={text(entry.id)}
              >
                <div>
                  <strong>{text(entry.role) || text(entry.event_type)}</strong>
                  <time>{date(entry.created_at)}</time>
                </div>
                {category === "conversations" ? (
                  <p>{text(entry.content)}</p>
                ) : (
                  <pre>{JSON.stringify(entry.payload, null, 2)}</pre>
                )}
              </div>
            ))
          )}
          <Pager
            name="entries"
            page={entries.data}
            offset={offset}
            onChange={setOffset}
          />
        </section>
      )}
      <details className="account-inspection-metadata">
        <summary>Saved parameters and provenance</summary>
        <pre>{JSON.stringify(metadata, null, 2)}</pre>
      </details>
    </article>
  );
}

function Workspace({ target }: { target: AccountUser }) {
  const { user } = useAccount();
  const client = useQueryClient();
  const [category, setCategory] = useState<Category>("conversations");
  const [selected, setSelected] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const base = `/admin/users/${target.id}/workspace`;
  const key = ["account-inspection", user?.id || "", target.id];
  useEffect(
    () => () => {
      const queryKey = ["account-inspection", user?.id || "", target.id];
      void client.cancelQueries({ queryKey });
      client.removeQueries({ queryKey });
    },
    [client, target.id, user?.id],
  );
  const summary = useQuery({
    queryKey: [...key, "overview"],
    queryFn: ({ signal }) => api<Overview>(base, { signal }),
  });
  const collection = useQuery({
    queryKey: [...key, "list", category, offset, search],
    queryFn: ({ signal }) =>
      api<Page<Row>>(
        `${base}/${category}?offset=${offset}&search=${encodeURIComponent(search)}`,
        { signal },
      ),
    enabled: !!summary.data,
  });
  const choose = (next: Category) => {
    setCategory(next);
    setSelected(null);
    setOffset(0);
    setSearch("");
  };
  return (
    <>
      <div className="account-inspection-toolbar">
        <span>
          <LockKeyhole size={14} /> Read only
        </span>
        <p>
          You remain signed in as {user?.display_name || user?.username}.
          Inspection cannot run or change anything.
        </p>
        <Button
          variant="ghost"
          aria-label="Refresh workspace"
          onClick={() => void client.invalidateQueries({ queryKey: key })}
        >
          <RefreshCw size={15} />
        </Button>
      </div>
      <ErrorNotice error={summary.error} />
      {summary.isPending ? (
        <Loading />
      ) : (
        !summary.error &&
        summary.data && (
          <div
            className={`account-inspection-layout ${selected ? "has-selection" : ""}`}
          >
            <nav className="account-inspection-nav" aria-label="Workspace data">
              {sections.map(([value, name, Icon]) => (
                <button
                  type="button"
                  key={value}
                  aria-current={value === category ? "page" : undefined}
                  aria-label={`${name} (${summary.data.counts[value]})`}
                  onClick={() => choose(value)}
                >
                  <Icon size={16} />
                  <span>{name}</span>
                  <small>{summary.data.counts[value]}</small>
                </button>
              ))}
              <details className="account-inspection-preferences">
                <summary>Personal preferences</summary>
                <pre>{JSON.stringify(summary.data.preferences, null, 2)}</pre>
              </details>
            </nav>
            <section
              className="account-inspection-browser"
              aria-label="Workspace records"
            >
              <label className="account-user-search">
                <Search size={16} />
                <span className="sr-only">Search workspace records</span>
                <input
                  type="search"
                  placeholder={`Search ${sections.find(([value]) => value === category)?.[1].toLowerCase()}…`}
                  value={search}
                  onChange={(event) => {
                    setSearch(event.target.value);
                    setOffset(0);
                    setSelected(null);
                  }}
                />
              </label>
              <ErrorNotice error={collection.error} />
              {collection.error ? null : collection.isPending ? (
                <Loading />
              ) : collection.data?.items.length === 0 ? (
                <Empty title="Nothing here yet">
                  No records match this view.
                </Empty>
              ) : (
                <ul className="account-inspection-list">
                  {collection.data?.items.map((row) => (
                    <li key={row.id}>
                      <button
                        type="button"
                        aria-pressed={selected === row.id}
                        onClick={() => setSelected(row.id)}
                      >
                        <strong>{row.title}</strong>
                        <span>
                          {row.status && <em>{label(row.status)}</em>}
                          <time>{date(row.created_at)}</time>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <Pager
                name="records"
                page={collection.data}
                offset={offset}
                onChange={(next) => {
                  setOffset(next);
                  setSelected(null);
                }}
              />
            </section>
            <section
              className="account-inspection-detail"
              aria-label="Record details"
            >
              {selected ? (
                <>
                  <Button
                    variant="ghost"
                    className="account-inspection-back"
                    onClick={() => setSelected(null)}
                  >
                    <ArrowLeft size={16} /> Back to records
                  </Button>
                  <Detail
                    key={`${category}:${selected}`}
                    category={category}
                    id={selected}
                    base={base}
                    queryKey={key}
                  />
                </>
              ) : (
                <Empty title="Choose a record">
                  Read conversations, inspect results and review saved
                  parameters here.
                </Empty>
              )}
            </section>
          </div>
        )
      )}
    </>
  );
}

export default function AccountInspection({
  target,
  onClose,
  returnFocusTo,
}: {
  target: AccountUser;
  onClose: () => void;
  returnFocusTo?: HTMLElement | null;
}) {
  const { user } = useAccount();
  if (!user?.is_admin) return null;
  return (
    <Dialog.Root
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content
          className="account-inspection-dialog"
          onCloseAutoFocus={(event) => {
            if (returnFocusTo?.isConnected) {
              event.preventDefault();
              returnFocusTo.focus({ preventScroll: true });
            }
          }}
        >
          <header>
            <div>
              <div className="eyebrow">Administrator inspection</div>
              <Dialog.Title>
                {target.display_name || target.username}’s workspace
              </Dialog.Title>
              <Dialog.Description>
                Private data belonging to {target.username}
                {!target.enabled ? " · Account disabled" : ""}.
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <Button variant="ghost" aria-label="Close workspace inspection">
                <X size={20} />
              </Button>
            </Dialog.Close>
          </header>
          <Workspace key={target.id} target={target} />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
