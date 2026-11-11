import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Film,
  ImagePlus,
  RefreshCw,
  SlidersHorizontal,
  Square,
} from "lucide-react";
import { api, type Run } from "../api";
import { useAccount } from "../account-context";
import { Badge, ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";
import { creativeJson } from "../components/creative/creative-project";
import VideoModelChoice from "../components/media/VideoModelChoice";
import { randomId } from "../lib/random-id";
import type { ImageModelCatalog } from "./image-models";
import { materialBase, type StudioRevision } from "./studio-material";

import {
  useShotProduction,
  terminal,
  type ShotProduction,
} from "./studio-production";

export default function StudioShotMedia({
  materialId,
  revision,
  scene,
  disabled,
  selectedArtifactId,
  onSelect,
}: {
  materialId: string;
  revision: StudioRevision;
  scene: number;
  disabled: boolean;
  selectedArtifactId?: string;
  onSelect: (id: string) => void;
}) {
  const { user } = useAccount();
  const cache = useQueryClient();
  const production = useShotProduction(materialId, revision.id);
  const [playbackError, setPlaybackError] = useState(false);
  const [settings, setSettings] = useState(false);
  const [imageModel, setImageModel] = useState("");
  const [videoModel, setVideoModel] = useState("");
  const receipt = useRef<{ key: string; id: string } | null>(null);
  const shot = revision.storyboard.scenes[scene];
  const video = shot.visual_kind === "video";
  const models = useQuery({
    queryKey: ["image-models"],
    enabled: settings && !video,
    queryFn: () => api<ImageModelCatalog>("/images/models"),
  });
  const runs = (production.data?.runs ?? []).filter(
    (r) => r.parameters.studio_scene === scene,
  );
  const active =
    runs.find((r) =>
      ["running", "preparing", "claimed", "cancel_requested"].includes(
        r.status,
      ),
    ) ?? runs.find((r) => !terminal.has(r.status));
  const takes = (production.data?.artifacts ?? []).filter(
    (a) => a.type === shot.visual_kind && runs.some((r) => r.id === a.run_id),
  );
  const source = selectedArtifactId
    ? takes.find((a) => a.id === selectedArtifactId)
    : takes[0];
  const sourceDuration = Number(
    source?.metadata?.duration_seconds ??
      Number(source?.metadata?.frames) / Number(source?.metadata?.fps),
  );
  const requiredDuration = shot.duration_frames / 30 + shot.media_start_seconds;
  const needsLonger =
    video &&
    source &&
    Number.isFinite(sourceDuration) &&
    sourceDuration + 1 / 120 < requiredDuration;

  const failed = runs.find(
    (r) =>
      r.task_id === runs[0]?.task_id &&
      (r.status === "failed" || r.status === "interrupted"),
  );
  function refresh() {
    void cache.invalidateQueries({
      queryKey: ["studio-production", user?.id, materialId, revision.id],
    });
    void cache.invalidateQueries({
      queryKey: ["studio-activity", user?.id, materialId],
    });
  }
  const generate = useMutation({
    mutationFn: () => {
      const body = {
        revision_id: revision.id,
        scene,
        ...(video
          ? videoModel
            ? { video_model_id: videoModel }
            : {}
          : imageModel
            ? { image_model: imageModel }
            : {}),
      };
      const key = JSON.stringify(body);
      if (receipt.current?.key !== key)
        receipt.current = { key, id: randomId() };
      return api<Run>(
        `${materialBase}/${materialId}/shots`,
        creativeJson("POST", {
          ...body,
          client_request_id: receipt.current.id,
        }),
      );
    },
    onSuccess: (run) => {
      receipt.current = null;
      onSelect("");
      cache.setQueryData<ShotProduction>(
        ["studio-production", user?.id, materialId, revision.id],
        (previous) => ({
          runs: [run, ...(previous?.runs ?? []).filter((r) => r.id !== run.id)],
          artifacts: previous?.artifacts ?? [],
        }),
      );
      refresh();
    },
  });
  const stop = useMutation({
    mutationFn: (run: Run) =>
      api(
        `${materialBase}/${materialId}/shots/${run.id}/stop`,
        creativeJson("POST", {}),
      ),
    onSuccess: refresh,
  });
  if (!video && shot.visual_kind !== "image") return null;
  return (
    <section
      className="studio-shot-production"
      aria-label={`Shot ${scene + 1} media`}
    >
      {source && (
        <div className="studio-generated-preview">
          {source.type === "video" ? (
            <video
              controls
              preload="metadata"
              playsInline
              src={`/api/artifacts/${source.id}/file`}
              aria-label={`Shot ${scene + 1} generated footage`}
              onLoadStart={() => setPlaybackError(false)}
              onLoadedMetadata={(event) => {
                const player = event.currentTarget;
                if (Number.isFinite(player.duration) && player.duration > 0)
                  player.currentTime = Math.min(0.04, player.duration / 2);
              }}
              onError={() => setPlaybackError(true)}
            />
          ) : (
            <img
              src={`/api/artifacts/${source.id}/file`}
              loading="lazy"
              alt={`Generated shot ${scene + 1}`}
            />
          )}
          <div>
            <span>{video ? "Generated footage" : "Generated image"}</span>
            <Link to={`/library/${source.id}`}>Open in Library ↗</Link>
          </div>
        </div>
      )}
      {needsLonger && (
        <p className="notice" role="status">
          This clip covers {sourceDuration.toFixed(1)}s; the measured edit needs{" "}
          {requiredDuration.toFixed(1)}s. Generate a longer take before
          exporting.
        </p>
      )}
      {playbackError && (
        <p className="studio-direction-note" role="status">
          This browser could not play the clip. Open it in Library to download
          the original.
        </p>
      )}
      {takes.length > 1 && (
        <label>
          Compare takes
          <select
            aria-label={`Shot ${scene + 1} take`}
            value={source?.id ?? ""}
            onChange={(e) => onSelect(e.target.value)}
          >
            {!source && (
              <option value="" disabled>
                Choose an available take
              </option>
            )}
            {takes.map((a, i) => (
              <option key={a.id} value={a.id}>
                Take {takes.length - i} ·{" "}
                {new Date(a.created_at).toLocaleString()}
              </option>
            ))}
          </select>
        </label>
      )}
      <div className="studio-shot-production-actions">
        <Button
          type="button"
          disabled={
            disabled || !!active || generate.isPending || production.isPending
          }
          onClick={() => generate.mutate()}
        >
          {source ? (
            <RefreshCw size={15} />
          ) : video ? (
            <Film size={15} />
          ) : (
            <ImagePlus size={15} />
          )}
          {generate.isPending
            ? "Queuing…"
            : source
              ? "Generate another take"
              : video
                ? "Generate footage"
                : "Generate image"}
        </Button>
        <Button
          type="button"
          variant="ghost"
          aria-expanded={settings}
          disabled={disabled || !!active}
          onClick={() => setSettings(!settings)}
        >
          <SlidersHorizontal size={15} />
          Model
        </Button>
        {active && (
          <>
            <Badge status={active.status} />
            <Button
              type="button"
              variant="ghost"
              disabled={stop.isPending}
              onClick={() => stop.mutate(active)}
            >
              <Square size={13} />
              Stop shot
            </Button>
          </>
        )}
      </div>
      {settings && (
        <div className="studio-shot-model">
          {video ? (
            <>
              <VideoModelChoice
                value={videoModel}
                onChange={setVideoModel}
                disabled={disabled || !!active}
              />
              <p>
                Uses the current video runtime and real continuation footage for
                the full shot. Native generation is widescreen; review framing
                before the final edit.
              </p>
            </>
          ) : (
            <label>
              Image model
              <select
                aria-label={`Shot ${scene + 1} image model`}
                value={imageModel}
                disabled={disabled || !!active}
                onChange={(e) => setImageModel(e.target.value)}
              >
                <option value="">Default · your image settings</option>
                {(models.data?.items ?? [])
                  .filter((m) =>
                    m.modes.includes(
                      shot.reference_artifact_ids.length ? "recompose" : "t2i",
                    ),
                  )
                  .map((m) => (
                    <option key={m.id} value={m.id} disabled={!m.available}>
                      {m.name}
                      {m.available ? "" : " · unavailable"}
                    </option>
                  ))}
              </select>
            </label>
          )}
        </div>
      )}
      {active && (
        <p className="studio-direction-note">
          {video
            ? "Generating and assembling the complete clip."
            : "Generating from this saved shot and its image references."}{" "}
          Other takes remain available.
        </p>
      )}
      {!active && failed && (
        <div className="notice" role="status">
          {failed.error_message || "A previous take needs inspection."}{" "}
          <Link to={`/runs/${failed.id}`}>Inspect Run</Link>
        </div>
      )}
      <ErrorNotice
        error={production.error ?? generate.error ?? stop.error ?? models.error}
      />
    </section>
  );
}
