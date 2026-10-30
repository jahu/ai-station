import { useEffect } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, type Run } from "../../api";
import { useMediaRun } from "../media/media-run";
import type { Source, Track } from "./timeline";

export default function Waveform({
  source,
  track,
  fps,
}: {
  source: Source;
  track: Track;
  fps: number;
}) {
  const request = useMutation({
    mutationFn: (id: string) =>
      api<Run>(`/timelines/waveforms/${id}`, { method: "POST" }),
  });
  const { mutate } = request;
  useEffect(() => {
    mutate(source.artifact_id);
  }, [source.artifact_id, mutate]);
  const live = useMediaRun(
    request.variables === source.artifact_id ? (request.data?.id ?? "") : "",
  );
  const run =
    request.variables === source.artifact_id
      ? (live.data ?? request.data)
      : undefined;
  const peaks = (run?.metadata?.waveform as { peaks?: number[] } | undefined)
    ?.peaks;
  if (!peaks)
    return (
      <span className="tl-waveform-state">
        {request.error || run?.status === "failed"
          ? "Waveform unavailable"
          : "Preparing waveform…"}
      </span>
    );
  const length = track.duration_frames / fps;
  const start = track.in_sample / (source.samples || 1);
  const span = (length * (source.sample_rate || 1)) / (source.samples || 1);
  const bars = Array.from({ length: 128 }, (_, i) => {
    const position = start + (i / 128) * span;
    const peak =
      position < 1
        ? (peaks[Math.min(511, Math.floor(position * 512))] ?? 0)
        : 0;
    const fade = Math.min(
      1,
      track.fade_in_frames
        ? ((i / 128) * track.duration_frames) / track.fade_in_frames
        : 1,
      track.fade_out_frames
        ? ((1 - i / 128) * track.duration_frames) / track.fade_out_frames
        : 1,
    );
    const height = Math.max(0, Math.min(1, peak * track.gain * fade)) * 18;
    return `M${i * 4},${24 - height}v${height * 2}`;
  }).join(" ");
  return (
    <svg
      className="tl-waveform"
      viewBox="0 0 512 48"
      preserveAspectRatio="none"
      role="img"
      aria-label="Source waveform with volume and fades"
    >
      <path d={bars} fill="none" stroke="currentColor" strokeWidth="2" />
    </svg>
  );
}
