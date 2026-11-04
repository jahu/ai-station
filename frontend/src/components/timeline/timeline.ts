export type Placement = {
  artifact_id: string;
  start_frame: number;
  gain: number;
  muted: boolean;
  fade_in_frames: number;
  fade_out_frames: number;
};
export type Clip = Placement & { in_frame: number; out_frame: number };
export type Track = Placement & { in_sample: number; duration_frames: number };
export type Manifest = {
  fps: 24 | 25;
  width: number;
  height: number;
  clips: Clip[];
  tracks: Track[];
};
export type Source = {
  artifact_id: string;
  kind: "video" | "audio";
  title: string;
  frames?: number;
  fps?: number;
  width?: number;
  height?: number;
  samples?: number;
  sample_rate?: number;
  channels?: number;
  capability?: string;
};
export type Revision = {
  id: string;
  session_id: string;
  position: number;
  manifest: Manifest;
  parent_revision_id: string | null;
  created_at: string;
};
export const emptyManifest = (): Manifest => ({
  fps: 24,
  width: 1280,
  height: 704,
  clips: [],
  tracks: [],
});
const place = (p: Partial<Placement>): Placement => ({
  artifact_id: String(p.artifact_id ?? ""),
  start_frame: p.start_frame ?? 0,
  gain: p.gain ?? 1,
  muted: p.muted ?? false,
  fade_in_frames: p.fade_in_frames ?? 0,
  fade_out_frames: p.fade_out_frames ?? 0,
});
export function normalize(value?: Partial<Manifest>): Manifest {
  return {
    fps: value?.fps === 25 ? 25 : 24,
    width: value?.width ?? 1280,
    height: value?.height ?? 704,
    clips: (value?.clips ?? []).map((c) => ({
      ...place(c),
      in_frame: c.in_frame ?? 0,
      out_frame: c.out_frame,
    })),
    tracks: (value?.tracks ?? []).map((t) => ({
      ...place(t),
      in_sample: t.in_sample ?? 0,
      duration_frames: t.duration_frames,
    })),
  };
}
export const signature = (m: Manifest) => JSON.stringify(normalize(m));
export const clipFrames = (
  clip: Clip,
  m: Manifest,
  sources: Record<string, Source>,
) =>
  Math.ceil(
    ((clip.out_frame - clip.in_frame) * m.fps) /
      (sources[clip.artifact_id]?.fps || m.fps),
  );
export const endFrame = (m: Manifest, sources: Record<string, Source>) =>
  Math.max(
    0,
    ...m.clips.map((c) => c.start_frame + clipFrames(c, m, sources)),
    ...m.tracks.map((t) => t.start_frame + t.duration_frames),
  );
export const clock = (seconds: number) => {
  const value = Math.max(0, Number.isFinite(seconds) ? seconds : 0);
  return `${Math.floor(value / 60)
    .toString()
    .padStart(2, "0")}:${(value % 60).toFixed(2).padStart(5, "0")}`;
};
export function errorFor(
  m: Manifest,
  sources: Record<string, Source>,
): string | null {
  if (!m.clips.length && !m.tracks.length)
    return "Add a video or audio track to begin.";
  if (m.clips.length > 16 || m.tracks.length > 16)
    return "Use at most 16 video clips and 16 audio tracks.";
  if (
    ![m.width, m.height].every(
      (v) => Number.isInteger(v) && v >= 128 && v <= 1280 && v % 32 === 0,
    ) ||
    m.width * m.height > 1280 * 704
  )
    return "Choose a supported film size.";
  const intervals: [number, number][] = [];
  for (const [kind, placements] of [
    ["video", m.clips],
    ["audio", m.tracks],
  ] as const) {
    for (const p of placements) {
      const s = sources[p.artifact_id];
      if (!s) return "Inspecting your source media…";
      if (
        s.kind !== kind ||
        !Number.isInteger(p.start_frame) ||
        p.start_frame < 0 ||
        !Number.isFinite(p.gain) ||
        p.gain < 0 ||
        p.gain > 4
      )
        return "Check clip positions and volume.";
      let count: number;
      if (kind === "video") {
        const c = p as Clip;
        if (
          !Number.isInteger(c.in_frame) ||
          !Number.isInteger(c.out_frame) ||
          c.in_frame < 0 ||
          c.out_frame <= c.in_frame ||
          c.out_frame > (s.frames || 0)
        )
          return "Keep video trims inside their source.";
        count = clipFrames(c, m, sources);
        intervals.push([p.start_frame, p.start_frame + count]);
      } else {
        const t = p as Track,
          rate = s.sample_rate || 1;
        if (
          !Number.isInteger(t.in_sample) ||
          t.in_sample < 0 ||
          t.in_sample >= (s.samples || 0) ||
          !Number.isInteger(t.duration_frames) ||
          t.duration_frames < 1 ||
          t.in_sample + Math.ceil((t.duration_frames * rate) / m.fps) >
            (s.samples || 0) + Math.ceil(rate / m.fps) - 1
        )
          return "Keep audio trims inside their source.";
        count = t.duration_frames;
      }
      if (
        ![p.fade_in_frames, p.fade_out_frames].every(
          (v) => Number.isInteger(v) && v >= 0,
        ) ||
        p.fade_in_frames + p.fade_out_frames > count
      )
        return "Keep fades inside the clip duration.";
    }
  }
  intervals.sort((a, b) => a[0] - b[0]);
  if (intervals.some((v, i) => i > 0 && intervals[i - 1][1] > v[0]))
    return "Video clips overlap. Move or trim them, or use Arrange clips.";
  if (endFrame(m, sources) > 300 * m.fps)
    return "Keep the complete film within five minutes.";
  return null;
}
export function retime(m: Manifest, fps: 24 | 25): Manifest {
  const factor = fps / m.fps;
  const common = (p: Placement) => ({
    ...p,
    start_frame: Math.round(p.start_frame * factor),
    fade_in_frames: Math.round(p.fade_in_frames * factor),
    fade_out_frames: Math.round(p.fade_out_frames * factor),
  });
  return {
    ...m,
    fps,
    clips: m.clips.map((c) => ({ ...c, ...common(c) })),
    tracks: m.tracks.map((t) => ({
      ...t,
      ...common(t),
      duration_frames: Math.ceil(t.duration_frames * factor),
    })),
  };
}
