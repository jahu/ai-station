import { useEffect, useRef, useState } from "react";
import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowDown,
  ArrowUp,
  Clapperboard,
  Download,
  Film,
  FolderOpen,
  Music2,
  Plus,
  Save,
  Settings2,
  Square,
  Trash2,
  Volume2,
  VolumeX,
} from "lucide-react";
import { api, type Artifact, type Run } from "../api";
import { accountEpoch } from "../lib/account-storage";
import { randomId } from "../lib/random-id";
import { Button } from "../components/ui/button";
import { ErrorNotice } from "../components/common";
import {
  useCreative,
  useCreativeDraft,
  creativeRun,
} from "../components/creative/creative-context";
import { mediaBusy, useMediaRun } from "../components/media/media-run";
import { MediaRunProgress } from "../components/media/GenerationProgress";
import Waveform from "../components/timeline/Waveform";
import NumberInput from "../components/timeline/NumberInput";
import {
  clipFrames,
  clock,
  endFrame,
  errorFor,
  normalize,
  retime,
  signature,
  type Clip,
  type Manifest,
  type Placement,
  type Revision,
  type Source,
  type Track,
} from "../components/timeline/timeline";
import "./TimelineEditor.css";

const json = (body: unknown) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
type Selection = { kind: "video" | "audio"; index: number };

export default function TimelineEditor() {
  const creative = useCreative();
  return <Editor key={creative?.formKey ?? "standalone"} />;
}

function Editor() {
  const creative = useCreative();
  const cache = useQueryClient();
  const [search] = useSearchParams();
  const epoch = useRef(accountEpoch());
  const [initial] = useState(() => creative?.draft ?? {});
  const restored = (initial.formState ?? initial) as Record<string, unknown>;
  const [manifest, setManifest] = useState<Manifest>(() =>
    normalize(restored.manifest as Manifest | undefined),
  );
  const [revision, setRevision] = useState<Revision | null>(null);
  const [parentRevision, setParentRevision] = useState(
    String(restored.revision_id ?? ""),
  );
  const [previewId, setPreviewId] = useState(
    String(restored.preview_run_id ?? ""),
  );
  const [selection, setSelection] = useState<Selection | null>(null);
  const [picker, setPicker] = useState<"video" | "audio" | null>(null);
  const [filter, setFilter] = useState("");
  const [zoom, setZoom] = useState(60);
  const [playhead, setPlayhead] = useState(0);
  const preview = useRef<HTMLVideoElement>(null);
  const audioPreview = useRef<HTMLAudioElement>(null);
  const latestManifest = useRef(manifest);
  useEffect(() => {
    latestManifest.current = manifest;
  }, [manifest]);
  const drag = useRef<{
    kind: "video" | "audio";
    index: number;
    x: number;
    frame: number;
  } | null>(null);
  const receipt = useRef<{ key: string; id: string } | null>(null);
  const staged = useRef("");
  const sourceIds = [
    ...new Set(
      [...manifest.clips, ...manifest.tracks].map((p) => p.artifact_id),
    ),
  ];
  const queries = useQueries({
    queries: sourceIds.map((id) => ({
      queryKey: ["timeline-source", id],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        api<Source>(`/timelines/sources/${id}`, { signal }),
      staleTime: 30000,
    })),
  });
  const sources = Object.fromEntries(
    queries.flatMap((q) => (q.data ? [[q.data.artifact_id, q.data]] : [])),
  ) as Record<string, Source>;
  const ready = useQuery({
    queryKey: ["timeline-capabilities"],
    queryFn: ({ signal }) =>
      api<{ available: boolean; readiness?: string; reason?: string }>(
        "/timelines/capabilities",
        { signal },
      ),
    refetchInterval: (q) =>
      q.state.data?.readiness === "checking" ? 1000 : false,
  });
  const revisions = useQuery({
    queryKey: ["timeline-revisions", creative?.id],
    queryFn: ({ signal }) =>
      api<Revision[]>(`/timelines/${creative!.id}/revisions`, { signal }),
    enabled: !!creative,
  });
  const assets = useQuery({
    queryKey: ["timeline-library", picker, filter],
    queryFn: ({ signal }) =>
      api<Artifact[]>(
        `/artifacts?kind=${picker}&search=${encodeURIComponent(filter)}&limit=100`,
        { signal },
      ),
    enabled: !!picker,
  });
  const activeId = previewId || creative?.sourceRun?.id || "";
  const run = useMediaRun(activeId);
  const artifacts = useQuery({
    queryKey: ["timeline-render-artifacts", activeId],
    queryFn: ({ signal }) =>
      api<Artifact[]>(`/artifacts?run_id=${activeId}`, { signal }),
    enabled: run.data?.status === "succeeded",
  });
  const output = artifacts.data?.find(
    (a) =>
      a.type === "video" && !a.trashed_at && !a.purge_run_id && !a.purged_at,
  );
  const matching =
    !!run.data &&
    signature(normalize(run.data.parameters.manifest as Manifest)) ===
      signature(manifest);
  const invalid = errorFor(manifest, sources);
  const rawTotal = endFrame(manifest, sources);
  const total = Number.isFinite(rawTotal)
    ? Math.max(0, Math.min(manifest.fps * 300, rawTotal))
    : 0;
  const [view, setView] = useState<"source" | "preview">("preview");
  const selected = selection
    ? (selection.kind === "video" ? manifest.clips : manifest.tracks)[
        selection.index
      ]
    : undefined;
  const source = selected ? sources[selected.artifact_id] : undefined;
  const busy = mediaBusy(run.data);
  const sourceError = queries.find((q) => q.error)?.error;
  useCreativeDraft({
    formState: {
      manifest,
      revision_id: parentRevision || undefined,
      preview_run_id: previewId || undefined,
    },
  });
  function sameAccount() {
    if (epoch.current !== accountEpoch())
      throw new Error("Account changed. Reopen the workspace.");
  }
  const add = useMutation({
    mutationFn: (id: string) => api<Source>(`/timelines/sources/${id}`),
    onSuccess: (info) => {
      if (epoch.current !== accountEpoch()) return;
      cache.setQueryData(["timeline-source", info.artifact_id], info);
      setSelection({
        kind: info.kind,
        index:
          info.kind === "video"
            ? manifest.clips.length
            : manifest.tracks.length,
      });
      setManifest((current) => {
        const placement: Placement = {
          artifact_id: info.artifact_id,
          start_frame: 0,
          gain: info.capability === "audio.music" ? 0.35 : 1,
          muted: false,
          fade_in_frames: 0,
          fade_out_frames: 0,
        };
        if (info.kind === "video") {
          const start = Math.max(
            0,
            ...current.clips.map(
              (c) =>
                c.start_frame +
                clipFrames(c, current, {
                  ...sources,
                  ...Object.fromEntries(
                    current.clips.flatMap((c) => {
                      const cached = cache.getQueryData<Source>([
                        "timeline-source",
                        c.artifact_id,
                      ]);
                      return cached ? [[c.artifact_id, cached]] : [];
                    }),
                  ),
                  [info.artifact_id]: info,
                }),
            ),
          );
          return {
            ...current,
            ...(!current.clips.length
              ? { width: info.width!, height: info.height! }
              : {}),
            clips: [
              ...current.clips,
              {
                ...placement,
                start_frame: start,
                in_frame: 0,
                out_frame: info.frames!,
              },
            ],
          };
        }
        return {
          ...current,
          tracks: [
            ...current.tracks,
            {
              ...placement,
              in_sample: 0,
              duration_frames: Math.ceil(
                (info.samples! * current.fps) / info.sample_rate!,
              ),
            },
          ],
        };
      });
      setPicker(null);
      setView("source");
    },
  });
  const { mutate: addMedia } = add;
  const input = search.get("input") ?? "";
  useEffect(() => {
    if (input && input !== staged.current) {
      staged.current = input;
      if (
        ![
          ...latestManifest.current.clips,
          ...latestManifest.current.tracks,
        ].some((p) => p.artifact_id === input)
      )
        addMedia(input);
    }
  }, [input, addMedia]);
  function update(patch: Partial<Placement & Clip & Track>) {
    if (!selection) return;
    setManifest((m) =>
      selection.kind === "video"
        ? {
            ...m,
            clips: m.clips.map((p, i) =>
              i === selection.index ? { ...p, ...patch } : p,
            ),
          }
        : {
            ...m,
            tracks: m.tracks.map((p, i) =>
              i === selection.index ? { ...p, ...patch } : p,
            ),
          },
    );
  }
  function move(kind: Selection["kind"], index: number, frame: number) {
    setManifest((m) =>
      kind === "video"
        ? {
            ...m,
            clips: m.clips.map((p, i) =>
              i === index ? { ...p, start_frame: Math.max(0, frame) } : p,
            ),
          }
        : {
            ...m,
            tracks: m.tracks.map((p, i) =>
              i === index ? { ...p, start_frame: Math.max(0, frame) } : p,
            ),
          },
    );
  }
  function arrange(values = manifest.clips) {
    let cursor = 0;
    const clips = values.map((p) => {
      const next = { ...p, start_frame: cursor };
      cursor += clipFrames(p, manifest, sources);
      return next;
    });
    setManifest((m) => ({ ...m, clips }));
  }
  async function ensureRevision() {
    sameAccount();
    if (!creative) throw new Error("Open a saved editing workspace first.");
    if (invalid) throw new Error(invalid);
    if (revision && signature(revision.manifest) === signature(manifest))
      return revision;
    const key = signature(manifest) + parentRevision;
    if (receipt.current?.key !== key) receipt.current = { key, id: randomId() };
    const next = await api<Revision>(
      `/timelines/${creative.id}/revisions`,
      json({
        client_request_id: receipt.current.id,
        manifest,
        ...(parentRevision ? { parent_revision_id: parentRevision } : {}),
      }),
    );
    sameAccount();
    setRevision(next);
    setParentRevision(next.id);
    void cache.invalidateQueries({
      queryKey: ["timeline-revisions", creative.id],
    });
    return next;
  }
  const save = useMutation({ mutationFn: ensureRevision });
  const render = useMutation({
    mutationFn: async () => {
      const saved = await ensureRevision();
      sameAccount();
      const result = creativeRun(
        await creative!.generate({
          revision_id: saved.id,
          manifest: saved.manifest,
        }),
      );
      sameAccount();
      setPreviewId(result.id);
      setView("preview");
      return result;
    },
  });
  const load = useMutation({
    mutationFn: async (id: string) => {
      const initialSignature = signature(manifest);
      const [saved, result] = await Promise.all([
        api<Revision>(`/timelines/revisions/${id}`),
        api<Run | null>(`/timelines/revisions/${id}/render`),
      ]);
      sameAccount();
      if (signature(latestManifest.current) !== initialSignature)
        throw new Error(
          "The draft changed while loading. Choose the saved edit again to replace it.",
        );
      setManifest(normalize(saved.manifest));
      setParentRevision(saved.id);
      setRevision(saved);
      setPreviewId(result?.id ?? "");
      setSelection(null);
      setView("preview");
    },
  });
  const stop = useMutation({
    mutationFn: () => api(`/runs/${activeId}/cancel`, { method: "POST" }),
    onSuccess: () =>
      void cache.invalidateQueries({ queryKey: ["run", activeId] }),
  });
  const working = save.isPending || render.isPending || load.isPending;
  const watchedClip =
    selection?.kind === "video" && selected
      ? (selected as Clip)
      : (manifest.clips.find(
          (c) =>
            c.start_frame <= playhead &&
            c.start_frame + clipFrames(c, manifest, sources) > playhead,
        ) ?? manifest.clips[0]);
  const watchedSource = watchedClip
    ? sources[watchedClip.artifact_id]
    : undefined;
  const shownVideo =
    view === "preview" && output
      ? `/api/artifacts/${output.id}/file`
      : watchedSource?.kind === "video"
        ? `/api/artifacts/${watchedSource.artifact_id}/file`
        : "";
  function seek(frame: number) {
    const value = Math.max(0, Math.min(total, frame));
    setPlayhead(value);
    if (!preview.current || preview.current.readyState < 1) return;
    if (view === "preview" && matching && output)
      preview.current.currentTime = value / manifest.fps;
    else if (watchedSource?.kind === "video" && watchedClip)
      preview.current.currentTime =
        watchedClip.in_frame / watchedSource.fps! +
        Math.max(0, (value - watchedClip.start_frame) / manifest.fps);
  }
  function block(
    p: Placement,
    kind: Selection["kind"],
    index: number,
    frames: number,
  ) {
    const info = sources[p.artifact_id];
    return (
      <button
        key={`${kind}-${index}`}
        type="button"
        className={`tl-block ${kind === "video" ? "tl-video-block" : "tl-audio-block"} ${p.muted ? "tl-muted" : ""} ${selection?.kind === kind && selection.index === index ? "tl-selected" : ""}`}
        style={{
          left: (p.start_frame / manifest.fps) * zoom,
          width: Math.max(24, (frames / manifest.fps) * zoom),
        }}
        aria-label={`${kind === "video" ? "Video clip" : "Audio track"} ${index + 1}: ${info?.title ?? "Loading"}`}
        onClick={() => {
          setSelection({ kind, index });
          setView("source");
        }}
        onPointerDown={(e) => {
          e.currentTarget.focus();
          e.currentTarget.setPointerCapture(e.pointerId);
          drag.current = { kind, index, x: e.clientX, frame: p.start_frame };
          setSelection({ kind, index });
        }}
        onPointerMove={(e) => {
          const d = drag.current;
          if (d?.kind === kind && d.index === index && e.buttons)
            move(
              kind,
              index,
              d.frame + Math.round(((e.clientX - d.x) / zoom) * manifest.fps),
            );
        }}
        onPointerUp={() => {
          drag.current = null;
        }}
        onPointerCancel={() => {
          drag.current = null;
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
            e.preventDefault();
            move(
              kind,
              index,
              p.start_frame +
                (e.key === "ArrowRight" ? 1 : -1) *
                  (e.shiftKey ? manifest.fps : 1),
            );
          }
        }}
      >
        <span>
          {p.muted ? (
            <VolumeX size={12} />
          ) : kind === "video" ? (
            <Film size={12} />
          ) : (
            <Music2 size={12} />
          )}
          {info?.title ?? "Inspecting source…"}
        </span>
        {kind === "audio" && info && (
          <Waveform source={info} track={p as Track} fps={manifest.fps} />
        )}
        <small>{clock(frames / manifest.fps)}</small>
      </button>
    );
  }
  return (
    <div className="tl-editor">
      <div className="tl-toolbar">
        <div>
          <Clapperboard size={20} />
          <strong>Your editing desk</strong>
          <span className="muted">
            {clock(total / manifest.fps)} · {manifest.width} × {manifest.height}
          </span>
        </div>
        <div>
          <Button
            type="button"
            variant="secondary"
            onClick={() => setPicker(picker === "video" ? null : "video")}
            disabled={manifest.clips.length >= 16}
          >
            <Plus size={14} /> Video
          </Button>
          <Button
            type="button"
            variant="secondary"
            onClick={() => setPicker(picker === "audio" ? null : "audio")}
            disabled={manifest.tracks.length >= 16}
          >
            <Plus size={14} /> Audio
          </Button>
          <Button
            type="button"
            variant="ghost"
            disabled={!!invalid || working}
            onClick={() => save.mutate()}
          >
            <Save size={14} />{" "}
            {save.isPending
              ? "Saving…"
              : revision && signature(revision.manifest) === signature(manifest)
                ? "Saved edit"
                : "Save edit"}
          </Button>
        </div>
      </div>
      {picker && (
        <section
          className="panel tl-library"
          aria-label="Choose timeline media"
        >
          <div className="tl-section-heading">
            <h3>
              {picker === "video"
                ? "Choose a film"
                : "Add speech, music or effects"}
            </h3>
            <Button
              type="button"
              variant="ghost"
              onClick={() => setPicker(null)}
            >
              Close
            </Button>
          </div>
          <label className="sr-only" htmlFor="tl-library-search">
            Search Library
          </label>
          <input
            id="tl-library-search"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Search your Library…"
          />
          {assets.isPending ? (
            <p>Loading your Library…</p>
          ) : (
            <div className="tl-asset-list">
              {assets.data
                ?.filter(
                  (a) =>
                    a.mime_type ===
                      (picker === "video" ? "video/mp4" : "audio/wav") &&
                    !a.trashed_at &&
                    !a.purged_at &&
                    !a.purge_run_id,
                )
                .map((a) => (
                  <Button
                    key={a.id}
                    type="button"
                    variant="secondary"
                    disabled={add.isPending}
                    onClick={() => add.mutate(a.id)}
                  >
                    <FolderOpen size={15} />
                    <span>{a.title || a.original_filename}</span>
                  </Button>
                ))}
              {!assets.data?.length && (
                <p className="muted">
                  Create media in the workspaces or upload a WAV in Audio, then
                  add it here.
                </p>
              )}
            </div>
          )}
        </section>
      )}
      <div className="tl-workspace">
        <section className="panel tl-preview" aria-label="Film preview">
          <div className="tl-section-heading">
            <h3>
              {view === "preview" && output
                ? matching
                  ? "Preview of this edit"
                  : "Preview of an earlier edit"
                : "Source preview"}
            </h3>
            <div>
              <button
                type="button"
                aria-pressed={view === "source"}
                onClick={() => setView("source")}
              >
                Source
              </button>
              <button
                type="button"
                aria-pressed={view === "preview"}
                disabled={!output}
                onClick={() => setView("preview")}
              >
                Rendered
              </button>
            </div>
          </div>
          {shownVideo ? (
            <video
              key={shownVideo}
              ref={preview}
              controls
              preload="metadata"
              src={shownVideo}
              aria-label="Editing preview"
              onLoadedMetadata={() => seek(playhead)}
              onPlay={() => audioPreview.current?.pause()}
              onTimeUpdate={(e) => {
                if (view === "preview" && matching)
                  setPlayhead(
                    Math.round(e.currentTarget.currentTime * manifest.fps),
                  );
              }}
            />
          ) : (
            <div className="tl-preview-empty">
              <Clapperboard size={40} />
              <h3>Bring your film together</h3>
              <p>
                Add clips and sound from your Library. Select a clip to watch
                its source; preview the saved edit when you are ready.
              </p>
            </div>
          )}
          {view === "source" && source?.kind === "audio" && selected && (
            <audio
              key={source.artifact_id}
              ref={audioPreview}
              controls
              preload="metadata"
              src={`/api/artifacts/${source.artifact_id}/file`}
              aria-label="Selected audio source preview"
              onPlay={() => preview.current?.pause()}
              onLoadedMetadata={(e) => {
                e.currentTarget.currentTime =
                  (selected as Track).in_sample / source.sample_rate!;
              }}
            />
          )}
          <input
            aria-label="Timeline playhead"
            type="range"
            min={0}
            max={Math.max(1, total)}
            step={1}
            value={Math.min(playhead, total)}
            disabled={!total}
            onChange={(e) => seek(Number(e.target.value))}
          />
          <div className="tl-preview-meta">
            <span>{clock(playhead / manifest.fps)}</span>
            <span>
              {output && !matching
                ? "Draft changed · preview again to hear this edit"
                : "Sources stay in Library · saved edits stay in this workspace"}
            </span>
          </div>
          {busy && run.data && (
            <div className="tl-render-progress">
              <MediaRunProgress runs={[run.data]} />
              <Button
                type="button"
                variant="ghost"
                onClick={() => stop.mutate()}
                disabled={stop.isPending}
              >
                <Square size={13} /> Stop render
              </Button>
            </div>
          )}
          <div className="tl-export">
            <Button
              type="button"
              disabled={!!invalid || working || busy || !ready.data?.available}
              onClick={() => render.mutate()}
            >
              <Clapperboard size={15} />{" "}
              {render.isPending
                ? "Saving and queuing…"
                : busy
                  ? "Rendering preview…"
                  : "Preview this edit"}
            </Button>
            {output && matching && (
              <Button asChild variant="secondary">
                <a href={`/api/artifacts/${output.id}/file`} download>
                  <Download size={15} /> Export film
                </a>
              </Button>
            )}
          </div>
          <p className="muted tl-caption">
            Preview and export use the same saved mix. Rendering runs on CPU and
            keeps your GPU models available.
            {output && matching
              ? " Your preview is already an export; no second render is needed."
              : ""}
          </p>
          {!ready.data?.available && (
            <p role="status" className="muted">
              {ready.data?.reason ?? "Checking timeline renderer…"}
            </p>
          )}
        </section>
        <section
          className="panel tl-inspector"
          aria-label="Selected clip controls"
        >
          <div className="tl-section-heading">
            <h3>
              {selection
                ? selection.kind === "video"
                  ? `Video clip ${selection.index + 1}`
                  : `Audio track ${selection.index + 1}`
                : "Clip controls"}
            </h3>
            <Settings2 size={16} />
          </div>
          {selected && source && selection ? (
            <>
              <p className="tl-source-name">{source.title}</p>
              <label>
                Start on timeline (seconds)
                <NumberInput
                  type="number"
                  min={0}
                  step="any"
                  value={Number(
                    (selected.start_frame / manifest.fps).toFixed(3),
                  )}
                  onChange={(e) =>
                    update({
                      start_frame: Math.round(
                        Number(e.target.value) * manifest.fps,
                      ),
                    })
                  }
                />
              </label>
              {selection.kind === "video" ? (
                <div className="tl-pair">
                  <label>
                    Source in (seconds)
                    <NumberInput
                      type="number"
                      min={0}
                      step="any"
                      value={Number(
                        ((selected as Clip).in_frame / source.fps!).toFixed(3),
                      )}
                      onChange={(e) =>
                        update({
                          in_frame: Math.round(
                            Number(e.target.value) * source.fps!,
                          ),
                        })
                      }
                    />
                  </label>
                  <label>
                    Source out (seconds)
                    <NumberInput
                      type="number"
                      min={0}
                      max={source.frames! / source.fps!}
                      step="any"
                      value={Number(
                        ((selected as Clip).out_frame / source.fps!).toFixed(3),
                      )}
                      onChange={(e) =>
                        update({
                          out_frame: Math.round(
                            Number(e.target.value) * source.fps!,
                          ),
                        })
                      }
                    />
                  </label>
                </div>
              ) : (
                <div className="tl-pair">
                  <label>
                    Source in (seconds)
                    <NumberInput
                      type="number"
                      min={0}
                      step="any"
                      value={Number(
                        (
                          (selected as Track).in_sample / source.sample_rate!
                        ).toFixed(3),
                      )}
                      onChange={(e) =>
                        update({
                          in_sample: Math.round(
                            Number(e.target.value) * source.sample_rate!,
                          ),
                        })
                      }
                    />
                  </label>
                  <label>
                    Duration (seconds)
                    <NumberInput
                      type="number"
                      min={1 / manifest.fps}
                      step="any"
                      value={Number(
                        (
                          (selected as Track).duration_frames / manifest.fps
                        ).toFixed(3),
                      )}
                      onChange={(e) =>
                        update({
                          duration_frames: Math.round(
                            Number(e.target.value) * manifest.fps,
                          ),
                        })
                      }
                    />
                  </label>
                </div>
              )}
              <label>
                {selection.kind === "video"
                  ? "Original sound volume"
                  : "Track volume"}{" "}
                · {Math.round(selected.gain * 100)}%
                <input
                  aria-label="Clip volume"
                  type="range"
                  min={0}
                  max={4}
                  step={0.01}
                  value={selected.gain}
                  onChange={(e) => update({ gain: Number(e.target.value) })}
                />
              </label>
              <label className="tl-check">
                <input
                  type="checkbox"
                  checked={selected.muted}
                  onChange={(e) => update({ muted: e.target.checked })}
                />
                <Volume2 size={14} /> Mute{" "}
                {selection.kind === "video" ? "original sound" : "track"}
              </label>
              <div className="tl-pair">
                <label>
                  Audio fade in (seconds)
                  <NumberInput
                    type="number"
                    min={0}
                    step="any"
                    value={Number(
                      (selected.fade_in_frames / manifest.fps).toFixed(3),
                    )}
                    onChange={(e) =>
                      update({
                        fade_in_frames: Math.round(
                          Number(e.target.value) * manifest.fps,
                        ),
                      })
                    }
                  />
                </label>
                <label>
                  Audio fade out (seconds)
                  <NumberInput
                    type="number"
                    min={0}
                    step="any"
                    value={Number(
                      (selected.fade_out_frames / manifest.fps).toFixed(3),
                    )}
                    onChange={(e) =>
                      update({
                        fade_out_frames: Math.round(
                          Number(e.target.value) * manifest.fps,
                        ),
                      })
                    }
                  />
                </label>
              </div>
              {selection.kind === "video" && (
                <div className="tl-pair">
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={selection.index === 0}
                    onClick={() => {
                      const i = selection.index,
                        clips = [...manifest.clips];
                      [clips[i - 1], clips[i]] = [clips[i], clips[i - 1]];
                      arrange(clips);
                      setSelection({ kind: "video", index: i - 1 });
                    }}
                  >
                    <ArrowUp size={14} /> Earlier
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={selection.index === manifest.clips.length - 1}
                    onClick={() => {
                      const i = selection.index,
                        clips = [...manifest.clips];
                      [clips[i + 1], clips[i]] = [clips[i], clips[i + 1]];
                      arrange(clips);
                      setSelection({ kind: "video", index: i + 1 });
                    }}
                  >
                    <ArrowDown size={14} /> Later
                  </Button>
                </div>
              )}
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  setManifest((m) =>
                    selection.kind === "video"
                      ? {
                          ...m,
                          clips: m.clips.filter(
                            (_, i) => i !== selection.index,
                          ),
                        }
                      : {
                          ...m,
                          tracks: m.tracks.filter(
                            (_, i) => i !== selection.index,
                          ),
                        },
                  );
                  setSelection(null);
                }}
              >
                <Trash2 size={14} /> Remove from timeline
              </Button>
              <small className="muted">
                Removing a clip keeps its source in Library. Source video sound
                follows its clip; separate tracks keep their own positions.
              </small>
            </>
          ) : (
            <p className="muted">
              Select a clip or track below. Drag to move it, use arrow keys for
              a frame, or Shift + arrows for one second.
            </p>
          )}
        </section>
      </div>
      <section
        className="panel tl-arrangement"
        aria-label="Multitrack timeline"
      >
        <div className="tl-section-heading">
          <h3>Timeline</h3>
          <div>
            <Button
              type="button"
              variant="ghost"
              onClick={() => arrange()}
              disabled={!manifest.clips.length}
            >
              Arrange clips
            </Button>
            <label className="tl-zoom">
              Zoom
              <input
                aria-label="Timeline zoom"
                type="range"
                min={20}
                max={160}
                value={zoom}
                onChange={(e) => setZoom(Number(e.target.value))}
              />
            </label>
          </div>
        </div>
        <div className="tl-scroll">
          <div
            className="tl-canvas"
            style={{
              width: 112 + Math.max(600, (total / manifest.fps) * zoom + 24),
            }}
          >
            <button
              type="button"
              className="tl-ruler"
              style={{
                width: Math.max(600, (total / manifest.fps) * zoom + 24),
              }}
              aria-label="Seek on timeline"
              onClick={(e) =>
                seek(
                  Math.round(
                    ((e.clientX -
                      e.currentTarget.getBoundingClientRect().left) /
                      zoom) *
                      manifest.fps,
                  ),
                )
              }
            >
              {Array.from(
                {
                  length: Math.min(
                    301,
                    Math.ceil(Math.max(6, total / manifest.fps)) + 1,
                  ),
                },
                (_, i) => (
                  <span key={i} style={{ left: i * zoom }}>
                    {clock(i)}
                  </span>
                ),
              )}
            </button>
            <div className="tl-lane">
              <strong>Video</strong>
              <div>
                {manifest.clips.map((c, i) =>
                  block(c, "video", i, clipFrames(c, manifest, sources)),
                )}
              </div>
            </div>
            {manifest.tracks.map((t, i) => (
              <div className="tl-lane" key={i}>
                <strong>
                  {sources[t.artifact_id]?.capability === "audio.music"
                    ? "Music"
                    : sources[t.artifact_id]?.capability === "audio.effects"
                      ? "Effects"
                      : `Audio ${i + 1}`}
                </strong>
                <div>{block(t, "audio", i, t.duration_frames)}</div>
              </div>
            ))}
            {!manifest.tracks.length && (
              <div className="tl-lane">
                <strong>Audio</strong>
                <div className="tl-empty-lane">
                  Add speech, music or effects · original sound stays with each
                  video clip
                </div>
              </div>
            )}
            <div
              className="tl-playhead"
              style={{ left: 112 + (playhead / manifest.fps) * zoom }}
            />
          </div>
        </div>
        <p className="tl-caption muted">
          Gaps in the video are black. Each audio track can be trimmed, moved,
          faded and muted independently. Peak protection prevents clipping in
          the rendered mix.
        </p>
      </section>
      <div className="tl-footer">
        <details>
          <summary>Film settings</summary>
          <div className="tl-pair">
            <label>
              Frame rate
              <select
                value={manifest.fps}
                onChange={(e) =>
                  setManifest((m) =>
                    retime(m, Number(e.target.value) as 24 | 25),
                  )
                }
              >
                <option value={24}>24 fps</option>
                <option value={25}>25 fps</option>
              </select>
            </label>
            <label>
              Film size
              <select
                value={`${manifest.width}x${manifest.height}`}
                onChange={(e) => {
                  const [width, height] = e.target.value.split("x").map(Number);
                  setManifest((m) => ({ ...m, width, height }));
                }}
              >
                {[
                  `${manifest.width}x${manifest.height}`,
                  "1280x704",
                  "768x512",
                  "512x768",
                  "512x512",
                ]
                  .filter((v, i, a) => a.indexOf(v) === i)
                  .map((v) => (
                    <option key={v} value={v}>
                      {v.replace("x", " × ")}
                    </option>
                  ))}
              </select>
            </label>
          </div>
        </details>
        <label>
          Saved edits
          <select
            aria-label="Saved timeline edits"
            value={parentRevision}
            onChange={(e) => {
              if (e.target.value) load.mutate(e.target.value);
            }}
          >
            <option value="">Choose a saved edit…</option>
            {revisions.data?.map((r) => (
              <option key={r.id} value={r.id}>
                Edit {r.position} · {new Date(r.created_at).toLocaleString()}
              </option>
            ))}
          </select>
        </label>
      </div>
      {invalid && (
        <p
          className="tl-validation"
          role={
            manifest.clips.length || manifest.tracks.length ? "alert" : "status"
          }
        >
          {invalid}
        </p>
      )}
      <ErrorNotice
        error={
          add.error ??
          save.error ??
          render.error ??
          load.error ??
          stop.error ??
          sourceError ??
          assets.error ??
          ready.error ??
          run.error
        }
      />
      {activeId && (
        <Link className="tl-run-link" to={`/runs/${activeId}`}>
          Render details and logs →
        </Link>
      )}
    </div>
  );
}
