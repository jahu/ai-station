import { Link, useParams, useNavigate } from "react-router-dom";
import {
  useQuery,
  useMutation,
  useInfiniteQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  useState,
  useRef,
  useEffect,
  useId,
  type KeyboardEvent,
} from "react";
import {
  Upload,
  Search,
  Trash2,
  AudioLines,
  Film,
  FileText,
  Image as ImageIcon,
} from "lucide-react";
import LibraryActions from "./LibraryActions";
import { api, type Artifact } from "../api";
import { ErrorNotice, Loading, PageTitle } from "../components/common";
import { Button } from "../components/ui/button";
import { time } from "../lib/utils";

function artifactName(artifact: Artifact) {
  return (
    artifact.title ||
    (artifact.metadata.mode
      ? ({
          t2i: "Generate",
          img2img: "Edit",
          recompose: "Recompose",
          upscale: "Upscale",
        }[artifact.metadata.mode] ?? artifact.metadata.mode)
      : artifact.original_filename)
  );
}

export function ArtifactCards({
  artifacts,
  heading = "Artifacts",
}: {
  artifacts: Artifact[];
  heading?: string;
}) {
  const headingId = useId();
  const labelId = useId();
  const listRef = useRef<HTMLDivElement>(null);
  const [selectedKey, setSelectedKey] = useState(artifacts[0]?.id ?? "");
  const found = artifacts.findIndex((artifact) => artifact.id === selectedKey);
  const index = found >= 0 ? found : 0;
  const focusItem = (next: number) => {
    const clamped = Math.max(0, Math.min(artifacts.length - 1, next));
    const artifact = artifacts[clamped];
    if (!artifact) return;
    setSelectedKey(artifact.id);
    const link = listRef.current?.querySelector<HTMLElement>(
      `[data-artifact-index="${clamped}"]`,
    );
    link?.focus();
    link?.scrollIntoView?.({ block: "nearest" });
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowRight") {
      event.preventDefault();
      focusItem(index + 1);
    } else if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
      event.preventDefault();
      focusItem(index - 1);
    } else if (event.key === "Home") {
      event.preventDefault();
      focusItem(0);
    } else if (event.key === "End") {
      event.preventDefault();
      focusItem(artifacts.length - 1);
    }
  };
  return (
    <section aria-labelledby={headingId}>
      <h2 id={headingId} className="sr-only">
        {heading}
      </h2>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose an artifact while the grid is focused. Enter inspects
        it.
      </p>
      <div
        ref={listRef}
        className="artifact-grid"
        aria-labelledby={labelId}
        onKeyDown={onKeyDown}
      >
        {artifacts.map((a, i) => {
          const current = i === index;
          const name = artifactName(a);
          return (
            <Link
              className="artifact-card panel"
              key={a.id}
              to={`/library/${a.id}`}
              aria-label={`Inspect ${name} ${a.id.slice(0, 8)}`}
              aria-current={current ? "true" : undefined}
              tabIndex={current ? 0 : -1}
              data-artifact-index={i}
              onFocus={() => setSelectedKey(a.id)}
            >
              {a.type === "image" ? (
                <img
                  loading="lazy"
                  src={`/api/artifacts/${a.id}/thumbnail`}
                  alt=""
                />
              ) : (
                <div className={`artifact-placeholder artifact-kind-${a.type}`}>
                  {a.type === "video" &&
                  a.metadata.capability === "avatar.animate" &&
                  a.parent_artifact_ids[0] ? (
                    <img
                      src={`/api/artifacts/${a.parent_artifact_ids[0]}/thumbnail`}
                      alt=""
                      loading="lazy"
                    />
                  ) : a.type === "audio" ? (
                    <AudioLines size={34} aria-hidden="true" />
                  ) : a.type === "video" ? (
                    <Film size={34} aria-hidden="true" />
                  ) : (
                    <FileText size={30} aria-hidden="true" />
                  )}
                  <span className="artifact-kind-label">
                    {a.type === "video" ? (
                      <Film size={12} aria-hidden="true" />
                    ) : a.type === "audio" ? (
                      <AudioLines size={12} aria-hidden="true" />
                    ) : null}
                    {a.type.replaceAll("_", " ")}
                  </span>
                </div>
              )}
              <div>
                <strong>{name}</strong>
                <span>
                  {a.metadata.backend ?? a.type}
                  {a.metadata.width
                    ? ` · ${a.metadata.width} × ${a.metadata.height}`
                    : ""}
                </span>
                <small>{time(a.created_at)}</small>
              </div>
            </Link>
          );
        })}
      </div>
    </section>
  );
}
export function Library() {
  const [kind, setKind] = useState("");
  const [view, setView] = useState("active");
  const [search, setSearch] = useState("");
  const [term, setTerm] = useState("");
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const cache = useQueryClient();
  useEffect(() => {
    const timer = setTimeout(() => setTerm(search.trim()), 250);
    return () => clearTimeout(timer);
  }, [search]);
  const query = useInfiniteQuery({
    queryKey: ["library", kind, view, term],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      api<Artifact[]>(
        `/artifacts?${new URLSearchParams({ kind, view, search: term, limit: "50", offset: String(pageParam) })}`,
      ),
    getNextPageParam: (last, pages) =>
      last.length === 50 ? pages.length * 50 : undefined,
  });
  const upload = useMutation({
    mutationFn: async (file: File) => {
      const audio =
        /\.wav$/i.test(file.name) ||
        ["audio/wav", "audio/x-wav"].includes(file.type);
      if (!audio && !/\.(png|jpe?g|webp)$/i.test(file.name))
        throw new Error("Import PNG, JPEG, WebP or PCM WAV files.");
      const body = new FormData();
      body.append("file", file);
      return api<Artifact>(audio ? "/audio/uploads" : "/images/uploads", {
        method: "POST",
        body,
      });
    },
    onSuccess: (artifact) => {
      void cache.invalidateQueries({ queryKey: ["library"] });
      navigate(`/library/${artifact.id}`);
    },
  });
  const artifacts = query.data?.pages.flat() ?? [];
  return (
    <>
      <PageTitle
        eyebrow="COLLECTION / LIBRARY"
        title={
          view === "trash"
            ? "Your Library trash."
            : "Everything you create, in one place."
        }
        action={
          <>
            <input
              ref={input}
              hidden
              type="file"
              accept="image/png,image/jpeg,image/webp,audio/wav,.wav"
              aria-label="Import artifact"
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                if (file) upload.mutate(file);
              }}
            />
            <Button
              disabled={upload.isPending}
              onClick={() => input.current?.click()}
            >
              <Upload size={16} />
              {upload.isPending ? "Importing…" : "Import file"}
            </Button>
          </>
        }
      >
        {" "}
        {view === "trash"
          ? "Restore artifacts whenever you need them. Files and execution history are preserved."
          : "Images, voices, videos and working files — with their source and history intact."}
      </PageTitle>
      <div className="library-toolbar">
        <div
          className="library-type-tabs"
          role="group"
          aria-label="Artifact type"
        >
          {[
            ["", "All"],
            ["image", "Images"],
            ["audio", "Audio"],
            ["video", "Video"],
            ["files", "Files"],
          ].map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={kind === value}
              onClick={() => setKind(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <button
          type="button"
          className={`library-trash-toggle ${view === "trash" ? "is-active" : ""}`}
          aria-pressed={view === "trash"}
          onClick={() => setView(view === "trash" ? "active" : "trash")}
        >
          <Trash2 size={15} />
          {view === "trash" ? "Back to Library" : "Trash"}
        </button>
      </div>
      <div className="library-search-row">
        <label>
          <Search size={16} />
          <span className="sr-only">Search Library</span>
          <input
            placeholder="Search names and notes…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <span>
          {artifacts.length} {query.hasNextPage ? "shown" : "artifacts"}
          {query.isFetching && !query.isFetchingNextPage ? " · updating" : ""}
        </span>
      </div>
      <ErrorNotice error={query.error ?? upload.error} />
      <div
        className={`library-drop-area ${dragging ? "is-dragging" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          if (!upload.isPending) setDragging(true);
        }}
        onDragLeave={(event) => {
          if (
            !(event.relatedTarget instanceof Node) ||
            !event.currentTarget.contains(event.relatedTarget)
          )
            setDragging(false);
        }}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          const file = event.dataTransfer.files[0];
          if (file && !upload.isPending) upload.mutate(file);
        }}
      >
        {dragging && (
          <div className="library-drop-overlay">
            <Upload size={30} />
            Drop a file to add it to Library
          </div>
        )}
        {query.isPending ? (
          <Loading />
        ) : artifacts.length ? (
          <ArtifactCards artifacts={artifacts} heading="Library" />
        ) : (
          <section className="panel library-empty">
            <ImageIcon size={36} />
            <h2>
              {term
                ? "No matching artifacts"
                : view === "trash"
                  ? "Your trash is empty"
                  : "Make room for your next idea."}
            </h2>
            <p>
              {term
                ? "Try another name, note or type filter."
                : view === "trash"
                  ? "Artifacts you move to Trash will appear here."
                  : "Drop an image or WAV here, import a file, or create something new."}
            </p>
            {view !== "trash" && !term && (
              <div>
                <Button asChild variant="secondary">
                  <Link to="/images">Create an image</Link>
                </Button>
                <Button asChild variant="ghost">
                  <Link to="/audio">Create speech</Link>
                </Button>
              </div>
            )}
          </section>
        )}
      </div>
      {query.hasNextPage && (
        <div className="library-load-more">
          <Button
            variant="secondary"
            disabled={query.isFetchingNextPage}
            onClick={() => void query.fetchNextPage()}
          >
            {query.isFetchingNextPage ? "Loading…" : "Load more artifacts"}
          </Button>
        </div>
      )}
    </>
  );
}
export function ArtifactDetail() {
  const { id } = useParams();
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState<Error | null>(null);
  const query = useQuery({
    queryKey: ["artifact", id],
    queryFn: () => api<Artifact>(`/artifacts/${id}`),
  });
  const a = query.data;
  const prompt =
    a?.metadata.edit_prompt || a?.metadata.prompt || a?.metadata.text || "";
  return (
    <>
      <Link className="back-link" to="/library">
        ← Library
      </Link>
      <PageTitle
        eyebrow="COLLECTION / INSPECTOR"
        title={a?.title || a?.original_filename || "Artifact"}
        action={a && <LibraryActions artifact={a} />}
      >
        Source, parameters, and execution history.
      </PageTitle>
      <ErrorNotice error={query.error ?? copyError} />
      {a?.trashed_at && (
        <div className="notice">
          <Trash2 size={16} />
          This artifact is in Trash. Restore it above to return it to Library.
        </div>
      )}
      {query.isPending ? (
        <Loading />
      ) : (
        a && (
          <div className="image-workspace">
            <section className="panel artifact-preview">
              {a.type === "image" && (
                <img
                  src={`/api/artifacts/${a.id}/file`}
                  alt={prompt || a.original_filename}
                />
              )}
              {a.type === "video" && (
                <video
                  controls
                  preload="metadata"
                  src={`/api/artifacts/${a.id}/file`}
                  aria-label="Generated video"
                  style={{ maxWidth: "100%" }}
                />
              )}
              {a.type === "audio" && (
                <audio
                  controls
                  preload="metadata"
                  src={`/api/artifacts/${a.id}/file`}
                  aria-label="Generated audio"
                />
              )}
              <a
                href={`/api/artifacts/${a.id}/file`}
                target="_blank"
                rel="noreferrer"
              >
                Open full artifact ↗
              </a>
            </section>
            <aside className="panel content-panel">
              <h2>Artifact details</h2>
              {a.notes && (
                <div className="library-notes">
                  <h3>Your notes</h3>
                  <p>{a.notes}</p>
                </div>
              )}
              <p>
                {a.metadata.width
                  ? `${a.metadata.width} × ${a.metadata.height} · `
                  : ""}
                {(a.size_bytes / 1024).toFixed(0)} KiB
              </p>
              <p className="muted">{time(a.created_at)}</p>
              {a.type === "image" && (
                <div className="artifact-actions">
                  {[
                    ["img2img", "Edit"],
                    ["recompose", "Recompose"],
                    ["upscale", "Upscale"],
                  ].map(([mode, label]) => (
                    <Button key={mode} asChild variant="secondary">
                      <Link to={`/images?mode=${mode}&input=${a.id}`}>
                        {label}
                      </Link>
                    </Button>
                  ))}
                </div>
              )}
              {a.type === "audio" && (
                <Button asChild variant="secondary">
                  <Link to={`/audio?input=${a.id}`}>
                    Use as voice reference
                  </Link>
                </Button>
              )}
              {prompt && (
                <>
                  <h3>{a.type === "audio" ? "Spoken text" : "Prompt"}</h3>
                  <p className="prompt-text">{prompt}</p>
                  <Button
                    variant="ghost"
                    onClick={() => {
                      void navigator.clipboard
                        .writeText(prompt)
                        .then(() => setCopied(true))
                        .catch(() =>
                          setCopyError(
                            new Error(
                              "Clipboard unavailable. Select and copy the prompt text.",
                            ),
                          ),
                        );
                    }}
                  >
                    {copied
                      ? "Copied"
                      : a.type === "audio"
                        ? "Copy text"
                        : "Copy prompt"}
                  </Button>
                </>
              )}
              {a.run_id && (
                <p>
                  <Link to={`/runs/${a.run_id}`}>Inspect source run →</Link>
                </p>
              )}
              {a.parent_artifact_ids.length > 0 && (
                <>
                  <h3>Source artifacts</h3>
                  <div className="source-strip">
                    {a.parent_artifact_ids.map((parent) => (
                      <Link key={parent} to={`/library/${parent}`}>
                        {a.type === "image" ? (
                          <img
                            src={`/api/artifacts/${parent}/thumbnail`}
                            alt={`Source ${parent.slice(0, 8)}`}
                          />
                        ) : (
                          `Reference ${parent.slice(0, 8)} →`
                        )}
                      </Link>
                    ))}
                  </div>
                </>
              )}
              <details>
                <summary>All parameters</summary>
                <pre>{JSON.stringify(a.metadata, null, 2)}</pre>
              </details>
            </aside>
          </div>
        )
      )}
    </>
  );
}
