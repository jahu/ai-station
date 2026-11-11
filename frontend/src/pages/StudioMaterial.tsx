import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  Archive,
  RotateCcw,
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  Check,
  Clapperboard,
  Film,
  Image,
  Layers,
  Save,
  Sparkles,
  Square,
  X,
} from "lucide-react";
import { api, type Artifact, type Run } from "../api";
import { useAccount } from "../account-context";
import { Badge, ErrorNotice, Loading, PageTitle } from "../components/common";
import { Button } from "../components/ui/button";
import { creativeJson } from "../components/creative/creative-project";
import LibraryPicker from "../components/media/LibraryPicker";
import { randomId } from "../lib/random-id";
import { useCreativeEntry } from "../components/creative/useCreativeEntry";
import UnifiedModelPicker, { type Catalog } from "./UnifiedModelPicker";
import {
  audioNames,
  formatNames,
  materialBase,
  type Storyboard,
  type StudioMaterial as Material,
  type StudioRevision,
  type StudioShot,
} from "./studio-material";
import StudioShotMedia from "./StudioShotMedia";
import StudioSoundtrack from "./StudioSoundtrack";
import StudioExport from "./StudioExport";
import "./Studio.css";
import "./StudioMaterial.css";

const terminal = new Set(["succeeded", "failed", "canceled", "interrupted"]);
const local = "local-openai-compatible";

export default function StudioMaterial() {
  const { id } = useParams();
  useCreativeEntry(id);
  const { user } = useAccount();
  const cache = useQueryClient();
  const [query, setQuery] = useSearchParams();
  const [dirty, setDirty] = useState(false);
  const material = useQuery({
    queryKey: ["studio-material", user?.id, id],
    queryFn: ({ signal }) => api<Material>(`${materialBase}/${id}`, { signal }),
  });
  const activity = useQuery({
    queryKey: ["studio-activity", user?.id, id],
    queryFn: ({ signal }) =>
      api<Run[]>(`${materialBase}/${id}/activity`, { signal }),
    refetchInterval: (q) =>
      q.state.data?.some((r) => !terminal.has(r.status)) ? 1500 : false,
  });
  const finished =
    activity.data
      ?.filter((r) => r.status === "succeeded")
      .map((r) => r.id)
      .join() ?? "";
  const revisions = useInfiniteQuery({
    queryKey: ["studio-revisions", user?.id, id, finished],
    initialPageParam: 0,
    queryFn: ({ signal, pageParam }) =>
      api<StudioRevision[]>(
        `${materialBase}/${id}/revisions?limit=30&offset=${pageParam}`,
        { signal },
      ),
    getNextPageParam: (last, pages) =>
      last.length === 30 ? pages.length * 30 : undefined,
  });
  const revisionRows = revisions.data?.pages.flat() ?? [];
  const wantedRevision = query.get("revision");
  const specificRevision = useQuery({
    queryKey: ["studio-revision", user?.id, id, wantedRevision],
    enabled:
      !!wantedRevision &&
      !!revisions.data &&
      !revisions.isFetching &&
      !revisionRows.some((r) => r.id === wantedRevision),
    queryFn: ({ signal }) =>
      api<StudioRevision>(`${materialBase}/${id}/revisions/${wantedRevision}`, {
        signal,
      }),
  });
  useEffect(() => {
    void cache.invalidateQueries({
      queryKey: ["studio-material", user?.id, id],
    });
  }, [cache, user?.id, id, finished]);
  const active = activity.data?.find(
    (r) => r.executor_type === "studio_director" && !terminal.has(r.status),
  );
  const completedPlan = activity.data?.find(
    (r) => r.id === query.get("planning_run") && r.status === "succeeded",
  );
  const plannedRevision =
    typeof completedPlan?.metadata?.studio_revision_id === "string"
      ? completedPlan.metadata.studio_revision_id
      : "";
  useEffect(() => {
    if (plannedRevision && !dirty)
      setQuery({ revision: plannedRevision }, { replace: true });
  }, [plannedRevision, dirty, setQuery]);
  const selected =
    revisionRows.find((r) => r.id === wantedRevision) ??
    specificRevision.data ??
    (!wantedRevision ? revisionRows[0] : undefined);
  const visibleRevisions =
    selected && !revisionRows.some((r) => r.id === selected.id)
      ? [selected, ...revisionRows]
      : revisionRows;
  const stop = useMutation({
    mutationFn: (runId: string) =>
      api(`/runs/${runId}/cancel`, { method: "POST" }),
    onSuccess: () =>
      cache.invalidateQueries({ queryKey: ["studio-activity", user?.id, id] }),
  });
  const archive = useMutation({
    mutationFn: () =>
      api<Material>(
        `${materialBase}/${id}`,
        creativeJson("PATCH", {
          expected_version: material.data!.version,
          archived: !material.data!.archived_at,
        }),
      ),
    onSuccess: () => {
      void cache.invalidateQueries({
        queryKey: ["studio-material", user?.id, id],
      });
      void cache.invalidateQueries({
        queryKey: ["studio-materials", user?.id],
      });
    },
  });
  if (material.isPending) return <Loading />;
  if (material.error) return <ErrorNotice error={material.error} />;
  const row = material.data!;
  const readOnly = !!row.archived_at;
  function saved(revision: StudioRevision) {
    setDirty(false);
    setQuery({ revision: revision.id });
    void cache.invalidateQueries({
      queryKey: ["studio-revisions", user?.id, id],
    });
    void cache.invalidateQueries({
      queryKey: ["studio-material", user?.id, id],
    });
  }
  return (
    <div
      className={`studio studio-material-workspace${selected ? " has-storyboard" : ""}`}
    >
      <Link
        className="studio-back"
        to={
          row.creative_project_id
            ? `/studio/${row.creative_project_id}`
            : "/studio"
        }
      >
        <ArrowLeft size={15} />
        {selected?.project_snapshot.name ?? "Studio"}
      </Link>
      <PageTitle
        eyebrow="STUDIO / MATERIAL"
        title={row.title}
        action={
          <Button
            variant="ghost"
            disabled={archive.isPending || dirty || !!active}
            onClick={() => archive.mutate()}
          >
            {readOnly ? <RotateCcw size={15} /> : <Archive size={15} />}
            {readOnly ? "Restore material" : "Archive material"}
          </Button>
        }
      >
        {formatNames[row.options.format]} · {row.options.aspect} ·{" "}
        {row.options.duration_seconds}s target · {audioNames[row.options.audio]}
      </PageTitle>
      <ErrorNotice
        error={
          revisions.error ??
          specificRevision.error ??
          activity.error ??
          stop.error ??
          archive.error
        }
      />
      {active && (
        <div className="studio-direction-progress" role="status">
          <Sparkles size={19} />
          <div>
            <strong>Developing your story</strong>
            <span>
              The director is planning the script, shots and sound. Your saved
              versions stay available.
            </span>
          </div>
          <Badge status={active.status} />
          <Button
            variant="ghost"
            disabled={stop.isPending}
            onClick={() => stop.mutate(active.id)}
          >
            <Square size={14} />
            Stop
          </Button>
        </div>
      )}
      {activity.data?.[0]?.status === "failed" && (
        <div className="notice" role="alert">
          {activity.data[0].error_message}
          <Link to={`/runs/${activity.data[0].id}`}>Inspect Run</Link>
        </div>
      )}
      <div className="studio-direction-layout">
        <section className="studio-storyboard" aria-label="Material storyboard">
          <div className="studio-material-heading">
            <div>
              <span className="eyebrow">SCRIPT & SHOTS</span>
              <h2>Your storyboard</h2>
            </div>
            {!!visibleRevisions.length && (
              <label className="studio-version-choice">
                <span className="sr-only">Storyboard version</span>
                <select
                  disabled={dirty}
                  aria-label="Storyboard version"
                  value={selected?.id}
                  onChange={(e) => {
                    setDirty(false);
                    setQuery({ revision: e.target.value });
                  }}
                >
                  {visibleRevisions.map((r) => (
                    <option key={r.id} value={r.id}>
                      Version {r.position} ·{" "}
                      {new Date(r.created_at).toLocaleString()}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          {revisions.hasNextPage && (
            <Button
              variant="ghost"
              disabled={dirty || revisions.isFetchingNextPage}
              onClick={() => void revisions.fetchNextPage()}
            >
              Load earlier versions
            </Button>
          )}
          {revisions.isPending || (specificRevision.isFetching && !selected) ? (
            <Loading />
          ) : selected ? (
            <StoryboardEditor
              key={selected.id}
              material={row}
              revision={selected}
              readOnly={readOnly || !!active}
              onDirty={() => setDirty(true)}
              onReset={() => setDirty(false)}
              onSaved={saved}
            />
          ) : (
            !revisions.error && (
              <div className="studio-storyboard-empty">
                <Clapperboard size={42} />
                <h2>An idea becomes a story</h2>
                <p>
                  Start with the director. Get a coherent script, a visual plan
                  for every beat, and a direction for the sound.
                </p>
                <span>
                  Every version stays here. Refine a single shot or develop
                  another take.
                </span>
              </div>
            )
          )}
        </section>
        <aside className="studio-direction-sidebar">
          <section className="panel studio-direction-brief">
            <span className="eyebrow">THE BRIEF</span>
            <p>{row.brief}</p>
            {selected?.project_snapshot.name && (
              <div className="studio-brand-reference">
                <Layers size={15} />
                <span>
                  {selected.project_snapshot.name}
                  <small>
                    Identity version {selected.project_snapshot.version}
                  </small>
                </span>
              </div>
            )}
          </section>
          <DirectorForm
            priorModel={
              typeof activity.data?.[0]?.parameters.model === "string"
                ? activity.data[0].parameters.model
                : undefined
            }
            material={row}
            revision={selected}
            busy={!!active || readOnly || dirty}
            onQueued={(run) => {
              cache.setQueryData<Run[]>(
                ["studio-activity", user?.id, id],
                (previous) => [
                  run,
                  ...(previous ?? []).filter((r) => r.id !== run.id),
                ],
              );
              setQuery({
                ...(selected ? { revision: selected.id } : {}),
                planning_run: run.id,
              });
              void cache.invalidateQueries({
                queryKey: ["studio-activity", user?.id, id],
              });
            }}
          />
          {dirty && (
            <p className="studio-direction-note">
              Save or discard your scene edits before planning another version.
            </p>
          )}
          <p className="studio-direction-note">
            The storyboard keeps your editorial intent. Generate images and
            footage beside each saved shot; every take stays in Library.
            Soundtrack production and final editing are the next steps.
          </p>
          {!!activity.data?.length && (
            <details className="studio-direction-history">
              <summary>Activity history · {activity.data.length}</summary>
              {activity.data.map((run) => (
                <Link key={run.id} to={`/runs/${run.id}`}>
                  <span>{new Date(run.created_at).toLocaleString()}</span>
                  <Badge status={run.status} />
                </Link>
              ))}
            </details>
          )}
        </aside>
      </div>
    </div>
  );
}

function DirectorForm({
  material,
  revision,
  busy,
  priorModel,
  onQueued,
}: {
  material: Material;
  revision?: StudioRevision;
  busy: boolean;
  priorModel?: string;
  onQueued: (run: Run) => void;
}) {
  const [feedback, setFeedback] = useState("");
  const [selectedModel, setModel] = useState("");
  const [references, setReferences] = useState<Artifact[]>([]);
  const receipt = useRef<{ fingerprint: string; id: string } | null>(null);
  const catalog = useQuery({
    queryKey: ["chat-model-catalog"],
    queryFn: () => api<Catalog>("/chat/model-catalog"),
    staleTime: 30000,
  });
  const choices = (catalog.data?.models ?? []).filter(
    (m) =>
      m.provider_key === local &&
      !["unavailable", "needs_inspection"].includes(m.availability),
  );
  const model =
    selectedModel ||
    choices.find((m) => m.model_key === priorModel)?.model_key ||
    choices.find((m) => m.availability === "ready")?.model_key ||
    choices[0]?.model_key ||
    "";
  const plan = useMutation({
    mutationFn: (body: unknown) =>
      api<Run>(
        `${materialBase}/${material.id}/plan`,
        creativeJson("POST", body),
      ),
    onSuccess: (run) => {
      setFeedback("");
      onQueued(run);
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    const body = {
      expected_version: material.version,
      model,
      feedback,
      parent_revision_id: revision?.id ?? null,
      reference_artifact_ids: references.map((r) => r.id),
    };
    const fingerprint = JSON.stringify(body);
    if (receipt.current?.fingerprint !== fingerprint)
      receipt.current = { fingerprint, id: randomId() };
    plan.mutate({ ...body, client_request_id: receipt.current.id });
  }
  return (
    <form className="panel studio-director-form" onSubmit={submit}>
      <div className="studio-director-label">
        <Sparkles size={18} />
        <h3>{revision ? "Develop another take" : "Meet your director"}</h3>
      </div>
      <p>
        {revision
          ? "Describe what to change in the saved version. Keep every earlier take."
          : "Your local model plans the narrative, imagery, motion and sound from the brief."}
      </p>
      <UnifiedModelPicker
        providerKey={local}
        modelKey={model}
        allowedProvider={local}
        location="local"
        busy={busy || plan.isPending}
        onSelect={(choice) => setModel(choice.model_key)}
      />
      <label>
        {revision ? "What should change?" : "Additional direction"}
        <textarea
          rows={4}
          value={feedback}
          maxLength={8000}
          disabled={busy || plan.isPending}
          placeholder={
            revision
              ? "A stronger opening, tighter narration, a different shot…"
              : "Anything else the director should keep in mind?"
          }
          onChange={(e) => setFeedback(e.target.value)}
        />
      </label>
      <LibraryPicker
        kind="image"
        existing={references.map((r) => r.id)}
        limit={12}
        busy={busy || plan.isPending}
        onSelect={(items) =>
          setReferences((previous) => [...previous, ...items].slice(0, 12))
        }
      />
      {!!references.length && (
        <div className="studio-reference-list">
          {references.map((a) => (
            <span key={a.id}>
              {a.title || a.original_filename}
              <button
                type="button"
                disabled={busy || plan.isPending}
                aria-label={`Remove ${a.title || a.original_filename}`}
                onClick={() =>
                  setReferences((items) => items.filter((i) => i.id !== a.id))
                }
              >
                <X size={13} />
              </button>
            </span>
          ))}
        </div>
      )}
      <ErrorNotice error={plan.error ?? catalog.error} />
      <Button type="submit" disabled={busy || plan.isPending || !model}>
        <Sparkles size={16} />
        {plan.isPending
          ? "Queuing…"
          : revision
            ? "Plan a new version"
            : "Prepare storyboard"}
      </Button>
    </form>
  );
}

function StoryboardEditor({
  material,
  revision,
  readOnly,
  onDirty,
  onReset,
  onSaved,
}: {
  material: Material;
  revision: StudioRevision;
  readOnly: boolean;
  onDirty: () => void;
  onReset: () => void;
  onSaved: (saved: StudioRevision) => void;
}) {
  const [board, setBoard] = useState<Storyboard>(revision.storyboard);
  const [takes, setTakes] = useState<Record<number, string>>({});
  const [dirty, setDirty] = useState(false);
  const receipt = useRef<{ fingerprint: string; id: string } | null>(null);
  function edit(next: Storyboard) {
    setBoard(next);
    setDirty(true);
    onDirty();
  }
  function change(index: number, value: Partial<StudioShot>) {
    edit({
      ...board,
      scenes: board.scenes.map((s, i) =>
        i === index ? { ...s, ...value } : s,
      ),
    });
  }
  function move(index: number, delta: number) {
    const scenes = [...board.scenes];
    [scenes[index], scenes[index + delta]] = [
      scenes[index + delta],
      scenes[index],
    ];
    edit({ ...board, scenes });
  }
  const save = useMutation({
    mutationFn: (body: unknown) =>
      api<StudioRevision>(
        `${materialBase}/${material.id}/revisions`,
        creativeJson("POST", body),
      ),
    onSuccess: onSaved,
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    const body = {
      expected_version: material.version,
      parent_revision_id: revision.id,
      storyboard: board,
    };
    const fingerprint = JSON.stringify(body);
    if (receipt.current?.fingerprint !== fingerprint)
      receipt.current = { fingerprint, id: randomId() };
    save.mutate({ ...body, client_request_id: receipt.current.id });
  }
  const frames = board.scenes.reduce((n, s) => n + s.duration_frames, 0);
  return (
    <form onSubmit={submit}>
      <div className="studio-story-summary">
        <h2>{board.title}</h2>
        <p>{board.concept}</p>
        <div>
          <span>{board.scenes.length} shots</span>
          <span>{(frames / 30).toFixed(1)}s planned</span>
          <span>{audioNames[board.audio]}</span>
        </div>
        <blockquote>{board.hook}</blockquote>
      </div>
      <fieldset className="studio-shots" disabled={readOnly || save.isPending}>
        {board.scenes.map((shot, index) => {
          const from = board.scenes
            .slice(0, index)
            .reduce((sum, item) => sum + item.duration_frames, 0);
          const end = from + shot.duration_frames;
          return (
            <article className="studio-shot" key={index}>
              <header>
                <span className="studio-shot-number">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <div>
                  <strong>{shot.purpose}</strong>
                  <small>
                    {(from / 30).toFixed(1)}–{(end / 30).toFixed(1)}s ·{" "}
                    {shot.visual_kind === "library"
                      ? "Library source"
                      : `Planned ${shot.visual_kind}`}
                  </small>
                </div>
                <div className="studio-shot-order">
                  <Button
                    variant="ghost"
                    type="button"
                    disabled={!index || readOnly || save.isPending}
                    aria-label={`Move shot ${index + 1} up`}
                    onClick={() => move(index, -1)}
                  >
                    <ArrowUp size={14} />
                  </Button>
                  <Button
                    variant="ghost"
                    type="button"
                    disabled={
                      index === board.scenes.length - 1 ||
                      readOnly ||
                      save.isPending
                    }
                    aria-label={`Move shot ${index + 1} down`}
                    onClick={() => move(index, 1)}
                  >
                    <ArrowDown size={14} />
                  </Button>
                </div>
              </header>
              {shot.source_artifact_id ? (
                <img
                  className="studio-shot-source"
                  src={`/api/artifacts/${shot.source_artifact_id}/thumbnail`}
                  alt="Selected Library source"
                />
              ) : (
                <div className="studio-shot-intent">
                  {shot.visual_kind === "video" ? (
                    <Film size={22} />
                  ) : (
                    <Image size={22} />
                  )}
                  <div>
                    <p>{shot.visual_brief || shot.body || shot.title}</p>
                    {shot.framing && <small>{shot.framing}</small>}
                  </div>
                </div>
              )}
              <StudioShotMedia
                materialId={material.id}
                revision={revision}
                scene={index}
                selectedArtifactId={takes[index]}
                onSelect={(id) =>
                  setTakes((value) => ({ ...value, [index]: id }))
                }
                disabled={readOnly || dirty || save.isPending}
              />
              {(shot.title || shot.eyebrow) && (
                <div className="studio-shot-overlay">
                  <small>ON SCREEN</small>
                  <span>
                    {[shot.eyebrow, shot.title].filter(Boolean).join(" · ")}
                  </span>
                </div>
              )}
              {shot.narration && (
                <div className="studio-shot-narration">
                  <small>VOICEOVER</small>
                  <p>{shot.narration}</p>
                </div>
              )}
              <details className="studio-shot-edit">
                <summary>Edit this shot</summary>
                <label>
                  Narrative purpose
                  <input
                    required
                    value={shot.purpose}
                    maxLength={500}
                    onChange={(e) => change(index, { purpose: e.target.value })}
                  />
                </label>
                <label>
                  Visual direction
                  <textarea
                    rows={4}
                    value={shot.visual_brief}
                    maxLength={2400}
                    onChange={(e) =>
                      change(index, { visual_brief: e.target.value })
                    }
                  />
                </label>
                <label>
                  Camera and framing
                  <textarea
                    rows={2}
                    value={shot.framing}
                    maxLength={500}
                    onChange={(e) => change(index, { framing: e.target.value })}
                  />
                </label>
                <label>
                  On-screen title
                  <input
                    value={shot.title}
                    maxLength={140}
                    onChange={(e) => change(index, { title: e.target.value })}
                  />
                </label>
                <label>
                  Duration · seconds
                  <input
                    type="number"
                    min={1}
                    max={90}
                    step="any"
                    required
                    value={shot.duration_frames / 30}
                    onChange={(e) =>
                      change(index, {
                        duration_frames: Math.round(
                          Number(e.target.value) * 30,
                        ),
                      })
                    }
                  />
                </label>
                {["voice", "voice_music"].includes(board.audio) && (
                  <label>
                    Spoken words
                    <textarea
                      rows={3}
                      maxLength={1000}
                      value={shot.narration}
                      onChange={(e) =>
                        change(index, { narration: e.target.value })
                      }
                    />
                  </label>
                )}
              </details>
            </article>
          );
        })}
        <section className="panel studio-sound-direction">
          <h3>Sound direction</h3>
          {["voice", "voice_music"].includes(board.audio) && (
            <label>
              Voice direction
              <textarea
                rows={2}
                value={board.voice_direction}
                maxLength={1000}
                onChange={(e) =>
                  edit({ ...board, voice_direction: e.target.value })
                }
              />
            </label>
          )}
          {["music", "voice_music"].includes(board.audio) && (
            <label>
              Music direction
              <textarea
                required
                rows={3}
                value={board.music_brief}
                maxLength={512}
                onChange={(e) =>
                  edit({ ...board, music_brief: e.target.value })
                }
              />
              <small>{board.music_brief.length} / 512 characters</small>
            </label>
          )}
          {board.audio === "silent" && (
            <p>This material is intentionally silent.</p>
          )}
        </section>
      </fieldset>
      <StudioSoundtrack
        materialId={material.id}
        revision={revision}
        disabled={readOnly || dirty || save.isPending}
        onMeasured={(id) =>
          api<StudioRevision>(
            `${materialBase}/${material.id}/revisions/${id}`,
          ).then(onSaved)
        }
      />
      <StudioExport
        materialId={material.id}
        revision={revision}
        selectedTakes={takes}
        readOnly={readOnly}
        disabled={dirty || save.isPending}
      />
      <ErrorNotice error={save.error} />
      <div className="studio-story-save">
        <span>
          {dirty ? (
            "Unsaved scene edits"
          ) : (
            <>
              <Check size={14} />
              Version {revision.position} saved
            </>
          )}
        </span>
        <div>
          {dirty && (
            <Button
              type="button"
              variant="ghost"
              disabled={save.isPending}
              onClick={() => {
                setBoard(revision.storyboard);
                setDirty(false);
                onReset();
              }}
            >
              Discard edits
            </Button>
          )}
          <Button disabled={!dirty || readOnly || save.isPending} type="submit">
            <Save size={15} />
            {save.isPending ? "Saving…" : "Save as new version"}
          </Button>
        </div>
      </div>
    </form>
  );
}
