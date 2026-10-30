import ImageModelSelection from "../media/ImageModelSelection";
import SpeechModelSelection from "../media/SpeechModelSelection";
import AddSoundLink from "../media/AddSoundLink";
import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  Archive,
  ArrowDown,
  ArrowUpRight,
  Check,
  ChevronDown,
  History,
  LoaderCircle,
  Plus,
  RotateCcw,
  Square,
  WandSparkles,
} from "lucide-react";
import { api, type Artifact } from "../../api";
import { useAccount } from "../../account-context";
import { accountEpoch, accountStorageKey } from "../../lib/account-storage";
import { randomId } from "../../lib/random-id";
import { Badge, ErrorNotice, Loading, PageTitle } from "../common";
import { Button } from "../ui/button";
import MediaJobResult from "../media/MediaJobResult";
import { MediaRunProgress } from "../media/GenerationProgress";
import PromptTranslation from "../media/PromptTranslation";
import ResourceWaitNotice from "../ResourceWaitNotice";
import {
  CreativeContext,
  type CreativeCapability,
  type CreativeDetail,
  type CreativeDraft,
  type CreativeSession,
  type CreativeTurn,
} from "./creative-context";
import "./CreativeWorkspace.css";

const names: Record<CreativeCapability, [string, string]> = {
  images: ["Images", "image"],
  video: ["Video", "film"],
  music: ["Music", "track"],
  speech: ["Speech", "voiceover"],
  avatars: ["Avatars", "avatar"],
  effects: ["Sound effects", "soundtrack"],
};
const terminal = new Set(["succeeded", "failed", "canceled", "interrupted"]);
const status = (turn: CreativeTurn) =>
  turn.status ?? turn.run?.status ?? "interrupted";
const busy = (turn: CreativeTurn) => !terminal.has(status(turn));
const progressRuns = (turn: CreativeTurn) =>
  turn.runs ?? (turn.run ? [turn.run] : []);
const hasProgress = (turn: CreativeTurn) =>
  progressRuns(turn).some(
    (run) => run.generation_progress && !terminal.has(run.status),
  );
const json = (method: string, body: unknown, keepalive = false) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
  keepalive,
});
const prompt = (turn: CreativeTurn) =>
  String(
    turn.parameters.edit_prompt ||
      turn.parameters.prompt ||
      turn.parameters.caption ||
      turn.parameters.text ||
      turn.parameters.speech_text ||
      "Generation with saved settings",
  );
const date = (value: string) =>
  new Date(value).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });

function readDraft(key: string): CreativeDraft | null {
  try {
    const value = JSON.parse(localStorage.getItem(key) ?? "null");
    return value && typeof value === "object" && !Array.isArray(value)
      ? (value as CreativeDraft)
      : null;
  } catch {
    return null;
  }
}

export default function CreativeWorkspace({
  capability,
  children,
}: {
  capability: CreativeCapability;
  children: ReactNode;
}) {
  const { user } = useAccount();
  const [search] = useSearchParams();
  const owner = user?.id ?? "operator";
  if (!search.has("session") && (search.has("run") || search.has("job")))
    return children;
  return (
    <Workspace
      key={`${owner}:${capability}`}
      capability={capability}
      owner={owner}
    >
      {children}
    </Workspace>
  );
}

function Workspace({
  capability,
  owner,
  children,
}: {
  capability: CreativeCapability;
  owner: string;
  children: ReactNode;
}) {
  const [search, setSearch] = useSearchParams();
  const [archived, setArchived] = useState(false);
  const [mobileHistory, setMobileHistory] = useState(false);
  const id = search.get("session") ?? "";
  const cache = useQueryClient();
  const listKey = ["creative-sessions", owner, capability, archived];
  const sessions = useInfiniteQuery({
    queryKey: listKey,
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      api<CreativeSession[]>(
        `/creative/sessions?capability=${capability}&archived=${archived}&limit=50&offset=${pageParam}`,
        { signal },
      ),
    getNextPageParam: (last, pages) =>
      last.length === 50
        ? pages.reduce((n, page) => n + page.length, 0)
        : undefined,
  });
  const sessionKey = ["creative-session", owner, id];
  const current = useQuery({
    queryKey: sessionKey,
    queryFn: ({ signal }) =>
      api<CreativeDetail>(`/creative/sessions/${id}`, { signal }),
    enabled: !!id,
    refetchInterval: (query) =>
      query.state.data?.turns.some(busy) ? 1500 : false,
  });
  function select(nextId: string, preserveInputs = false) {
    setSearch((previous) => {
      const next = new URLSearchParams(previous);
      next.set("session", nextId);
      for (const key of ["run", "job"]) next.delete(key);
      if (!preserveInputs) {
        for (const key of ["input", "image", "audio", "model"])
          next.delete(key);
        if (capability === "images") next.delete("mode");
      }
      return next;
    });
    setMobileHistory(false);
  }
  const create = useMutation<CreativeSession, Error, boolean>({
    mutationFn: () =>
      api<CreativeSession>(
        "/creative/sessions",
        json("POST", { capability, title: `Untitled ${names[capability][1]}` }),
      ),
    onSuccess: (row, preserveInputs) => {
      cache.setQueryData(["creative-session", owner, row.id], {
        ...row,
        turns: [],
        next_before: null,
      });
      select(row.id, preserveInputs);
      setArchived(false);
      void cache.invalidateQueries({
        queryKey: ["creative-sessions", owner, capability],
      });
    },
  });
  const bootstrap = useRef(false);
  useEffect(() => {
    if (id || !sessions.isSuccess || archived || bootstrap.current) return;
    bootstrap.current = true;
    const previous = sessions.data.pages.flat()[0];
    const hasSource = ["input", "image", "audio"].some((key) =>
      search.has(key),
    );
    if (previous && !hasSource)
      setSearch(
        (current) => {
          const next = new URLSearchParams(current);
          next.set("session", previous.id);
          return next;
        },
        { replace: true },
      );
    else create.mutate(hasSource);
    // A single initial decision; explicit New/History actions take over afterwards.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, sessions.isSuccess, archived]);
  const rows = sessions.data?.pages.flat() ?? [];
  return (
    <>
      <PageTitle
        eyebrow="CREATE / YOUR WORKSPACES"
        title={names[capability][0]}
        action={
          <Button
            onClick={() => create.mutate(false)}
            disabled={create.isPending}
          >
            <Plus size={16} /> New {names[capability][1]}
          </Button>
        }
      >
        Keep the idea, every version and its results together.
      </PageTitle>
      <ErrorNotice error={create.error ?? sessions.error} />
      <button
        type="button"
        className="creative-mobile-toggle"
        onClick={() => setMobileHistory(!mobileHistory)}
        aria-expanded={mobileHistory}
      >
        <History size={16} /> Your workspaces <ChevronDown size={14} />
      </button>
      <div className="creative-layout">
        <aside
          className={`creative-sidebar ${mobileHistory ? "is-open" : ""}`}
          aria-label="Creative workspaces"
        >
          <div className="creative-sidebar-label">
            <History size={15} /> Your workspaces
          </div>
          <div className="creative-list-tabs">
            <button
              type="button"
              aria-pressed={!archived}
              onClick={() => setArchived(false)}
            >
              Recent
            </button>
            <button
              type="button"
              aria-pressed={archived}
              onClick={() => setArchived(true)}
            >
              Archived
            </button>
          </div>
          {sessions.isPending ? <Loading /> : null}
          <nav>
            {rows.map((row) => (
              <button
                key={row.id}
                type="button"
                className={row.id === id ? "active" : ""}
                onClick={() => select(row.id)}
                aria-current={row.id === id ? "page" : undefined}
              >
                <span>{row.title}</span>
                <small>{date(row.updated_at)}</small>
              </button>
            ))}
          </nav>
          {!sessions.isPending && !rows.length && (
            <p className="creative-small-empty">
              {archived
                ? "No archived workspaces."
                : "Your ideas will appear here."}
            </p>
          )}
          {sessions.hasNextPage && (
            <Button
              variant="secondary"
              disabled={sessions.isFetchingNextPage}
              onClick={() => void sessions.fetchNextPage()}
            >
              More workspaces
            </Button>
          )}
        </aside>
        <section
          className="creative-main"
          aria-label="Current creative workspace"
        >
          <ErrorNotice error={current.error} />
          {current.isPending ? (
            <Loading />
          ) : current.data?.capability !== capability ? (
            <p className="muted">
              Choose a {names[capability][1]} workspace from history.
            </p>
          ) : (
            <SessionBody
              key={id}
              row={current.data}
              sessionKey={sessionKey}
              onChanged={() =>
                void cache.invalidateQueries({
                  queryKey: ["creative-sessions", owner, capability],
                })
              }
            >
              {children}
            </SessionBody>
          )}
        </section>
      </div>
    </>
  );
}

function SessionBody({
  row,
  sessionKey,
  onChanged,
  children,
}: {
  row: CreativeDetail;
  sessionKey: string[];
  onChanged: () => void;
  children: ReactNode;
}) {
  const cache = useQueryClient();
  const navigate = useNavigate();
  const storageKey = accountStorageKey(`ai-station:creative:${row.id}`);
  const [initial] = useState(() => readDraft(storageKey) ?? row.draft);
  const [draft, setDraftState] = useState<CreativeDraft>(initial);
  const draftRef = useRef(initial);
  const version = useRef(row.version);
  const serverTitle = useRef(row.title);
  const saved = useRef(JSON.stringify(row.draft));
  const queue = useRef<Promise<void>>(Promise.resolve());
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const epoch = useRef(accountEpoch());
  const alive = useRef(true);
  const [dirty, setDirty] = useState(
    JSON.stringify(initial) !== JSON.stringify(row.draft),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [formRevision, setFormRevision] = useState(0);
  const [editorOpen, setEditorOpen] = useState(row.turns.length === 0);
  const [title, setTitle] = useState(row.title);
  const [older, setOlder] = useState<CreativeTurn[]>([]);
  const [before, setBefore] = useState(row.next_before);
  const receipt = useRef<{ signature: string; id: string } | null>(null);
  const [pending, setPending] = useState(false);
  const end = useRef<HTMLDivElement>(null);

  function remember(value: CreativeDraft) {
    draftRef.current = value;
    setDraftState(value);
    setDirty(JSON.stringify(value) !== saved.current);
    try {
      localStorage.setItem(storageKey, JSON.stringify(value));
    } catch {
      /* Server saving remains available. */
    }
  }
  function updateCache(next: CreativeSession) {
    version.current = next.version;
    serverTitle.current = next.title;
    cache.setQueryData<CreativeDetail>(sessionKey, (current) =>
      current ? { ...current, ...next } : { ...row, ...next },
    );
  }
  function serialized<T>(operation: () => Promise<T>): Promise<T> {
    const result = queue.current.then(operation);
    queue.current = result.then(
      () => undefined,
      () => undefined,
    );
    return result;
  }
  async function saveSnapshot(keepalive = false) {
    if (epoch.current !== accountEpoch())
      throw new Error("Account changed; this draft was not sent.");
    const snapshot = JSON.stringify(draftRef.current);
    if (snapshot === saved.current) return;
    if (alive.current) setSaving(true);
    try {
      const next = await api<CreativeSession>(
        `/creative/sessions/${row.id}`,
        json(
          "PATCH",
          { expected_version: version.current, draft: draftRef.current },
          keepalive,
        ),
      );
      updateCache(next);
      saved.current = snapshot;
      if (alive.current) {
        setDirty(JSON.stringify(draftRef.current) !== snapshot);
        setError(null);
      }
      if (JSON.stringify(draftRef.current) === snapshot) {
        try {
          localStorage.removeItem(storageKey);
        } catch {
          /* Browser storage is optional. */
        }
      }
    } finally {
      if (alive.current) setSaving(false);
    }
  }
  function flush(keepalive = false) {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    return serialized(() => saveSnapshot(keepalive));
  }
  const flushRef = useRef(flush);
  useEffect(() => {
    flushRef.current = flush;
  });
  useEffect(() => {
    alive.current = true;
    const save = () => {
      void flushRef.current(true).catch(() => undefined);
    };
    window.addEventListener("pagehide", save);
    return () => {
      alive.current = false;
      window.removeEventListener("pagehide", save);
      save();
    };
  }, []);
  function setDraft(value: CreativeDraft) {
    const parent = draftRef.current._creative_parent_turn_id;
    const next = parent
      ? { ...value, _creative_parent_turn_id: parent }
      : value;
    if (JSON.stringify(next) === JSON.stringify(draftRef.current)) return;
    remember(next);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      void flush().catch((failure: Error) => {
        if (alive.current) setError(failure);
      });
    }, 400);
  }
  function metadata(values: Record<string, unknown>) {
    return serialized(async () => {
      await saveSnapshot();
      const next = await api<CreativeSession>(
        `/creative/sessions/${row.id}`,
        json("PATCH", { expected_version: version.current, ...values }),
      );
      updateCache(next);
      onChanged();
    });
  }
  async function generate(
    parameters: CreativeDraft,
    options?: { kind?: "direct" | "job"; feedback?: string },
  ) {
    setPending(true);
    try {
      return await serialized(async () => {
        await saveSnapshot();
        const body = {
          parameters,
          ...(options?.kind === "job" ? { request_kind: "job" } : {}),
          ...(draftRef.current._creative_parent_turn_id
            ? { parent_turn_id: draftRef.current._creative_parent_turn_id }
            : {}),
          feedback: options?.feedback ?? "",
        };
        const signature = JSON.stringify(body);
        if (receipt.current?.signature !== signature)
          receipt.current = { signature, id: randomId() };
        const turn = await api<CreativeTurn>(
          `/creative/sessions/${row.id}/generate`,
          json("POST", { ...body, client_request_id: receipt.current.id }),
        );
        const next = await cache.fetchQuery({
          queryKey: sessionKey,
          queryFn: () => api<CreativeDetail>(`/creative/sessions/${row.id}`),
          // Submission changed the server version even when the app's normal
          // query cache still considers the pre-submission snapshot fresh.
          staleTime: 0,
        });
        version.current = next.version;
        serverTitle.current = next.title;
        saved.current = JSON.stringify(next.draft);
        await saveSnapshot();
        if (
          !row.turns.length &&
          serverTitle.current === `Untitled ${names[row.capability][1]}`
        ) {
          const description = String(
            parameters.edit_prompt ||
              parameters.prompt ||
              parameters.caption ||
              parameters.text ||
              parameters.speech_text ||
              "",
          )
            .trim()
            .split("\n")[0];
          if (description) {
            const title =
              description.length > 68
                ? description.slice(0, 65) + "…"
                : description;
            const renamed = await api<CreativeSession>(
              `/creative/sessions/${row.id}`,
              json("PATCH", { expected_version: version.current, title }),
            );
            updateCache(renamed);
            setTitle(renamed.title);
          }
        }
        receipt.current = null;
        setEditorOpen(false);
        setOlder((current) => [
          ...current,
          ...row.turns.filter(
            (turn) => !current.some((saved) => saved.id === turn.id),
          ),
        ]);
        onChanged();
        setTimeout(
          () =>
            end.current?.scrollIntoView?.({
              block: "nearest",
              behavior:
                typeof window.matchMedia === "function" &&
                window.matchMedia("(prefers-reduced-motion: reduce)").matches
                  ? "auto"
                  : "smooth",
            }),
          50,
        );
        return turn;
      });
    } finally {
      setPending(false);
    }
  }
  function continueFrom(turn: CreativeTurn, artifact?: Artifact) {
    const parameters = {
      ...turn.parameters,
      _creative_parent_turn_id: turn.id,
    };
    if (row.capability === "avatars")
      Object.assign(parameters, { fullRecording: turn.request_kind === "job" });
    if (row.capability === "images" && artifact?.type === "image") {
      Object.assign(parameters, {
        mode: "img2img",
        input_artifact_ids: [artifact.id],
        edit_prompt: "",
        prompt_style: "instruction",
        upscale_result: false,
        video_prompt: null,
      });
    }
    remember(parameters);
    setFormRevision((value) => value + 1);
    setEditorOpen(true);
  }
  const loadOlder = useMutation({
    mutationFn: () =>
      api<CreativeDetail>(`/creative/sessions/${row.id}?before=${before}`),
    onSuccess: (next) => {
      setOlder((current) => [...next.turns, ...current]);
      setBefore(next.next_before);
    },
  });
  const stop = useMutation({
    mutationFn: (turn: CreativeTurn) =>
      api(
        `/creative/sessions/${row.id}/turns/${turn.id}/cancel`,
        json("POST", {}),
      ),
    onSuccess: () => void cache.invalidateQueries({ queryKey: sessionKey }),
  });
  const turns = [
    ...older.filter(
      (turn) => !row.turns.some((current) => current.id === turn.id),
    ),
    ...row.turns,
  ];
  return (
    <CreativeContext.Provider
      value={{
        id: row.id,
        formKey: `${row.id}:${formRevision}`,
        draft,
        setDraft,
        sourceRun:
          (draft._creative_parent_turn_id
            ? turns.find((turn) => turn.id === draft._creative_parent_turn_id)
            : turns.at(-1)
          )?.run ?? undefined,
        generate,
      }}
    >
      <div className="creative-session-heading">
        <div>
          <input
            aria-label="Workspace name"
            value={title}
            maxLength={160}
            onChange={(event) => setTitle(event.target.value)}
            onBlur={() => {
              if (title.trim() && title !== row.title)
                void metadata({ title: title.trim() }).catch(setError);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter") event.currentTarget.blur();
            }}
          />
          <span className="creative-save-state" aria-live="polite">
            {saving ? (
              <>
                <LoaderCircle size={12} /> Saving draft
              </>
            ) : dirty ? (
              "Draft kept on this device"
            ) : (
              <>
                <Check size={12} /> Saved
              </>
            )}
          </span>
        </div>
        <Button
          variant="ghost"
          aria-label={
            row.archived_at ? "Restore workspace" : "Archive workspace"
          }
          disabled={pending}
          onClick={() =>
            void metadata({ archived: !row.archived_at }).catch(setError)
          }
        >
          {row.archived_at ? <RotateCcw size={16} /> : <Archive size={16} />}
        </Button>
      </div>
      <ErrorNotice error={error ?? loadOlder.error ?? stop.error} />
      {error && (
        <div className="creative-save-recovery">
          <Button
            variant="secondary"
            onClick={() => void flush().catch(setError)}
          >
            Retry saving
          </Button>
          <Button
            variant="ghost"
            onClick={() => {
              void cache
                .fetchQuery({
                  queryKey: sessionKey,
                  queryFn: () =>
                    api<CreativeDetail>(`/creative/sessions/${row.id}`),
                  staleTime: 0,
                })
                .then((next) => {
                  version.current = next.version;
                  saved.current = JSON.stringify(next.draft);
                  remember(next.draft);
                  setTitle(next.title);
                  setError(null);
                  setFormRevision((value) => value + 1);
                });
            }}
          >
            Reload saved version
          </Button>
        </div>
      )}
      {before && (
        <Button
          variant="ghost"
          disabled={loadOlder.isPending}
          onClick={() => loadOlder.mutate()}
        >
          <ArrowUpRight size={14} /> Earlier versions
        </Button>
      )}
      <section className="creative-timeline" aria-label="Creation history">
        {turns.map((turn) => (
          <article key={turn.id} className="creative-turn">
            <div className="creative-turn-request">
              <span className="eyebrow">VERSION {turn.position}</span>
              <p>{prompt(turn)}</p>
              <time dateTime={turn.created_at}>
                {new Date(turn.created_at).toLocaleTimeString(undefined, {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </time>
            </div>
            <div className="creative-turn-result">
              <div className="creative-result-meta">
                <Badge status={status(turn)} />
                <Link to={`/runs/${turn.run_id}`}>
                  Details and logs <ArrowUpRight size={12} />
                </Link>
              </div>
              <ImageModelSelection run={turn.run ?? undefined} />
              <SpeechModelSelection
                run={turn.run ?? undefined}
                preparation={turn.runs?.find(
                  (run) =>
                    run.id ===
                    turn.run?.parameters?.reference_transcription_run_id,
                )}
              />
              {!turn.job &&
                progressRuns(turn)
                  .filter((run) => !!run.metadata?.prompt_translation)
                  .map((run) => (
                    <PromptTranslation
                      key={run.id}
                      run={run}
                      onRetried={(next) => navigate(`/runs/${next.id}`)}
                    />
                  ))}
              {!turn.job && turn.run?.status === "queued" && (
                <ResourceWaitNotice wait={turn.run.resource_wait} />
              )}
              {!turn.job && busy(turn) && (
                <div
                  className={`creative-working ${hasProgress(turn) ? "creative-measured" : ""}`}
                >
                  {hasProgress(turn) ? (
                    <MediaRunProgress runs={progressRuns(turn)} />
                  ) : (
                    <>
                      <LoaderCircle size={18} />
                      <span>
                        {status(turn) === "waiting_for_approval"
                          ? "Waiting for your prompt review"
                          : status(turn) === "cancel_requested"
                            ? "Stopping generation…"
                            : status(turn) === "queued"
                              ? "Queued · waiting to start"
                              : "Creating your next version…"}
                      </span>
                    </>
                  )}
                  <Button
                    variant="ghost"
                    disabled={stop.isPending}
                    onClick={() => stop.mutate(turn)}
                  >
                    <Square size={12} /> Stop
                  </Button>
                </div>
              )}
              {!turn.job && (turn.error_message || turn.run?.error_message) && (
                <p className="creative-result-error">
                  {turn.error_message || turn.run?.error_message}
                </p>
              )}
              {turn.job ? (
                <MediaJobResult
                  id={turn.task_id}
                  job={turn.job}
                  spokenText={
                    typeof turn.parameters.speech_text === "string"
                      ? turn.parameters.speech_text
                      : undefined
                  }
                />
              ) : (
                <div className="creative-artifacts">
                  {(row.capability === "effects"
                    ? [...turn.artifacts].sort(
                        (a, b) =>
                          Number(b.type === "video") -
                          Number(a.type === "video"),
                      )
                    : turn.artifacts
                  ).map((artifact) => (
                    <div key={artifact.id} className="creative-artifact">
                      {artifact.purged_at || artifact.purge_run_id ? (
                        <p className="muted">
                          This result is no longer available.
                        </p>
                      ) : (
                        <>
                          {artifact.type === "image" ? (
                            <img
                              src={`/api/artifacts/${artifact.id}/file`}
                              alt={artifact.title || "Generated image"}
                              loading="lazy"
                            />
                          ) : artifact.type === "video" ? (
                            <video
                              src={`/api/artifacts/${artifact.id}/file`}
                              controls
                              preload="metadata"
                            />
                          ) : (
                            <audio
                              src={`/api/artifacts/${artifact.id}/file`}
                              controls
                              preload="metadata"
                            />
                          )}
                          <div className="creative-artifact-actions">
                            <Link to={`/library/${artifact.id}`}>
                              Open in Library <ArrowUpRight size={12} />
                            </Link>
                            <AddSoundLink artifact={artifact} />
                            {artifact.type === "image" &&
                              row.capability === "images" &&
                              !row.archived_at && (
                                <Button
                                  variant="secondary"
                                  onClick={() => continueFrom(turn, artifact)}
                                >
                                  <WandSparkles size={14} /> Edit this image
                                </Button>
                              )}
                          </div>
                        </>
                      )}
                    </div>
                  ))}
                </div>
              )}
              {!busy(turn) && !row.archived_at && (
                <Button variant="ghost" onClick={() => continueFrom(turn)}>
                  <RotateCcw size={14} /> Use these settings
                </Button>
              )}
            </div>
          </article>
        ))}
        <div ref={end} />
      </section>
      {row.archived_at ? (
        <div className="creative-archived">
          <Archive size={20} />
          <p>
            This workspace is archived. Its history and results are retained.
          </p>
          <Button
            onClick={() => void metadata({ archived: false }).catch(setError)}
          >
            Restore to continue
          </Button>
        </div>
      ) : (
        <>
          {turns.length > 0 && (
            <div className="creative-next-version">
              <Button
                variant={editorOpen ? "ghost" : "secondary"}
                onClick={() => setEditorOpen(!editorOpen)}
              >
                <Plus size={16} />{" "}
                {editorOpen
                  ? "Hide generation settings"
                  : "Create next version"}
              </Button>
              <span>Every version stays in this workspace.</span>
            </div>
          )}
          {editorOpen && (
            <section
              className="creative-editor"
              aria-label="Generation settings"
              aria-busy={pending}
            >
              {children}
            </section>
          )}
          {!turns.length && (
            <div className="creative-first-hint">
              <ArrowDown size={14} /> Your first result and every variation will
              be saved here.
            </div>
          )}
        </>
      )}
    </CreativeContext.Provider>
  );
}
