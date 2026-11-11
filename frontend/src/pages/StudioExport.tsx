import { useRef, useState } from "react";
import StudioRendererSetup from "./StudioRendererSetup";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clapperboard, Download, Film, Square } from "lucide-react";
import { api, type Artifact, type Run } from "../api";
import { useAccount } from "../account-context";
import { Badge, ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";
import LibraryPicker from "../components/media/LibraryPicker";
import { creativeJson } from "../components/creative/creative-project";
import { randomId } from "../lib/random-id";
import {
  audioNames,
  materialBase,
  sourceEndSeconds,
  type StudioRevision,
} from "./studio-material";
import {
  useShotProduction,
  useStudioRenderer,
  terminal,
  type ShotProduction,
} from "./studio-production";

export default function StudioExport({
  materialId,
  revision,
  selectedTakes,
  disabled,
  readOnly,
}: {
  materialId: string;
  revision: StudioRevision;
  selectedTakes: Record<number, string>;
  disabled: boolean;
  readOnly: boolean;
}) {
  const { user } = useAccount();
  const [setupOpen, setSetupOpen] = useState(false);
  const cache = useQueryClient();
  const shots = useShotProduction(materialId, revision.id);
  const [selected, setSelected] = useState("");
  const [customSound, setCustomSound] = useState<Artifact | null>(null);
  const [playbackError, setPlaybackError] = useState(false);
  const receipt = useRef<{ fingerprint: string; id: string } | null>(null);
  const key = ["studio-exports", user?.id, materialId, revision.id];
  const history = useQuery({
    queryKey: key,
    queryFn: ({ signal }) =>
      api<ShotProduction>(
        `${materialBase}/${materialId}/exports?revision_id=${revision.id}`,
        { signal },
      ),
    refetchInterval: (q) =>
      q.state.data?.runs.some((r) => !terminal.has(r.status)) ? 1500 : false,
  });
  const renderer = useStudioRenderer();
  const silent = revision.storyboard.audio === "silent";
  const audio = useQuery({
    queryKey: ["studio-audio-productions", user?.id, materialId, revision.id],
    enabled: !silent,
    queryFn: ({ signal }) =>
      api<
        {
          measured_revision_id: string | null;
          soundtrack: Artifact | null;
          active_run_ids: string[];
        }[]
      >(
        `${materialBase}/${materialId}/audio/productions?revision_id=${revision.id}`,
        { signal },
      ),
    refetchInterval: (q) =>
      q.state.data?.some((r) => r.active_run_ids.length) ? 1500 : false,
  });
  const soundtrack =
    customSound ??
    audio.data?.find(
      (p) => p.measured_revision_id === revision.id && p.soundtrack,
    )?.soundtrack;
  const bindings: { scene: number; artifact_id: string }[] = [];
  const missing: number[] = [],
    short: number[] = [];
  revision.storyboard.scenes.forEach((shot, scene) => {
    if (shot.visual_kind !== "image" && shot.visual_kind !== "video") return;
    const runs = (shots.data?.runs ?? []).filter(
      (r) => r.parameters.studio_scene === scene,
    );
    const takes = (shots.data?.artifacts ?? []).filter(
      (a) => a.type === shot.visual_kind && runs.some((r) => r.id === a.run_id),
    );
    const picked = selectedTakes[scene]
      ? takes.find((a) => a.id === selectedTakes[scene])
      : takes[0];
    if (!picked) {
      missing.push(scene + 1);
      return;
    }
    bindings.push({ scene, artifact_id: picked.id });
    const duration = Number(
      picked.metadata.duration_seconds ??
        Number(picked.metadata.frames) / Number(picked.metadata.fps),
    );
    if (
      shot.visual_kind === "video" &&
      Number.isFinite(duration) &&
      duration + 1 / 120 < sourceEndSeconds(revision.storyboard.scenes, scene)
    )
      short.push(scene + 1);
  });
  const runs = history.data?.runs ?? [];
  const active = runs.find((r) => !terminal.has(r.status));
  const chosen = runs.find((r) => r.id === selected) ?? active ?? runs[0];
  const video = history.data?.artifacts.find((a) => a.run_id === chosen?.id);
  const busyShots = shots.data?.runs.some((r) => !terminal.has(r.status));
  const frames = revision.storyboard.scenes.reduce(
    (sum, s) => sum + s.duration_frames,
    0,
  );
  const dimensions = {
    portrait: "1080 × 1920",
    landscape: "1920 × 1080",
    square: "1080 × 1080",
  }[revision.options.aspect];
  function refresh() {
    void cache.invalidateQueries({ queryKey: key });
    void cache.invalidateQueries({
      queryKey: ["studio-activity", user?.id, materialId],
    });
  }
  const render = useMutation({
    mutationFn: () => {
      const body = {
        revision_id: revision.id,
        bindings,
        soundtrack_artifact_id: silent ? null : soundtrack?.id,
      };
      const fingerprint = JSON.stringify(body);
      if (receipt.current?.fingerprint !== fingerprint)
        receipt.current = { fingerprint, id: randomId() };
      return api<Run>(
        `${materialBase}/${materialId}/render`,
        creativeJson("POST", {
          ...body,
          client_request_id: receipt.current.id,
        }),
      );
    },
    onSuccess: (run) => {
      receipt.current = null;
      setSelected(run.id);
      cache.setQueryData<ShotProduction>(key, (previous) => ({
        runs: [run, ...(previous?.runs ?? [])],
        artifacts: previous?.artifacts ?? [],
      }));
      refresh();
    },
  });
  const stop = useMutation({
    mutationFn: (id: string) => api(`/runs/${id}/cancel`, { method: "POST" }),
    onSuccess: refresh,
  });
  const blocked =
    disabled ||
    readOnly ||
    !!active ||
    render.isPending ||
    shots.isPending ||
    history.isPending ||
    !!busyShots ||
    !renderer.data?.available ||
    missing.length > 0 ||
    short.length > 0 ||
    (!silent && !soundtrack);
  return (
    <section className="panel studio-export" aria-label="Export material">
      <header>
        <Clapperboard size={24} />
        <div>
          <h3>
            {video ? "Your story, ready to share" : "Bring it all together"}
          </h3>
          <p>
            {dimensions} · 30 fps · {(frames / 30).toFixed(1)}s ·{" "}
            {audioNames[revision.storyboard.audio]}
          </p>
        </div>
        <span className="studio-export-format">Full HD</span>
      </header>
      {video && (
        <div className="studio-export-result">
          <video
            controls
            playsInline
            preload="metadata"
            src={`/api/artifacts/${video.id}/file`}
            aria-label="Exported film"
            onLoadStart={() => setPlaybackError(false)}
            onError={() => setPlaybackError(true)}
            onLoadedMetadata={(e) => {
              const player = e.currentTarget;
              if (player.duration > 0)
                player.currentTime = Math.min(0.04, player.duration / 2);
            }}
          />
          <div>
            <Link to={`/library/${video.id}`}>Open in Library ↗</Link>
            <a
              href={`/api/artifacts/${video.id}/file`}
              download={video.original_filename}
            >
              <Download size={15} /> Download MP4
            </a>
          </div>
        </div>
      )}
      {playbackError && (
        <p className="notice">
          This browser could not play the film. Download the original MP4 to
          watch it.
        </p>
      )}
      {runs.length > 1 && (
        <label>
          Export versions
          <select
            aria-label="Export version"
            value={chosen?.id ?? ""}
            onChange={(e) => setSelected(e.target.value)}
          >
            {runs.map((r, i) => (
              <option key={r.id} value={r.id}>
                Export {runs.length - i} · {r.status}
              </option>
            ))}
          </select>
        </label>
      )}
      {active && (
        <div className="studio-export-progress" role="status">
          <Film size={20} />
          <div>
            <strong>Rendering your film</strong>
            <span>
              Using the saved storyboard, selected takes and complete
              soundtrack.
            </span>
          </div>
          <Badge status={active.status} />
          <Button
            type="button"
            variant="ghost"
            disabled={stop.isPending}
            onClick={() => stop.mutate(active.id)}
          >
            <Square size={13} /> Stop export
          </Button>
          <Link to={`/runs/${active.id}`}>Inspect Run ↗</Link>
        </div>
      )}
      {chosen &&
        ["failed", "interrupted", "canceled"].includes(chosen.status) && (
          <p className="notice" role="alert">
            {chosen.error_message ||
              (chosen.status === "canceled"
                ? "Export stopped. Your shots and soundtrack are kept."
                : "This export did not finish. Your earlier results are kept.")}{" "}
            <Link to={`/runs/${chosen.id}`}>Inspect Run</Link>
          </p>
        )}
      {missing.length > 0 && (
        <p className="studio-direction-note">
          Finish the actual media for shot{missing.length > 1 ? "s" : ""}{" "}
          {missing.join(", ")} above.
        </p>
      )}
      {short.length > 0 && (
        <p className="notice" role="status">
          Shot{short.length > 1 ? "s" : ""} {short.join(", ")} need
          {short.length === 1 ? "s" : ""} longer footage for the measured
          narration. Generate a longer take above.
        </p>
      )}
      {!silent && !soundtrack && (
        <p className="studio-direction-note">
          Create and apply the complete soundtrack above before exporting.
        </p>
      )}
      {!renderer.data?.available && !renderer.isPending && (
        <div>
          <p className="studio-direction-note">
            {renderer.data?.reason ||
              "Prepare local film export to finish this story."}
          </p>
          {renderer.data?.readiness !== "checking" && (
            <Button
              type="button"
              variant="secondary"
              aria-expanded={setupOpen}
              onClick={() => setSetupOpen((open) => !open)}
            >
              {setupOpen ? "Hide export setup" : "Set up film export"}
            </Button>
          )}
          {setupOpen && <StudioRendererSetup />}
        </div>
      )}
      {readOnly && (
        <p className="studio-direction-note">
          Restore this material to create another export. Existing films remain
          available.
        </p>
      )}
      {disabled && (
        <p className="studio-direction-note">
          Save your scene edits before exporting.
        </p>
      )}
      {!silent && (
        <details className="studio-export-audio">
          <summary>Use a different complete mix</summary>
          <p className="studio-direction-note">
            Choose a final 48-kHz stereo WAV that covers this entire saved edit.
            Raw voice passages are not a finished soundtrack.
          </p>
          <LibraryPicker
            kind="audio"
            existing={soundtrack ? [soundtrack.id] : []}
            limit={1}
            busy={disabled || readOnly || !!active}
            onSelect={(items) => setCustomSound(items[0] ?? null)}
          />
          {customSound && (
            <div className="studio-export-audio-choice">
              {customSound.title || customSound.original_filename}
              <Button
                type="button"
                variant="ghost"
                disabled={!!active}
                onClick={() => setCustomSound(null)}
              >
                Use Studio soundtrack
              </Button>
            </div>
          )}
        </details>
      )}
      <ErrorNotice
        error={
          shots.error ??
          history.error ??
          renderer.error ??
          audio.error ??
          render.error ??
          stop.error
        }
      />
      <Button type="button" disabled={blocked} onClick={() => render.mutate()}>
        <Clapperboard size={17} />
        {render.isPending
          ? "Queuing export…"
          : video
            ? "Export another version"
            : "Export film"}
      </Button>
      <p className="studio-direction-note">
        The selected takes are frozen for this export. Every earlier film stays
        in Library.
      </p>
    </section>
  );
}
