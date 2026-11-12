import type { CreativeDefaults } from "../components/creative/creative-project";

export interface NarrationWords {
  minimum?: number;
  maximum?: number;
}
export interface StudioOptions extends CreativeDefaults {
  narration_words?: NarrationWords | null;
}

export function narrationWordCount(board: Storyboard): number {
  return board.scenes.reduce(
    (count, shot) =>
      count +
      shot.narration.split(/\s+/).filter((word) => /[\p{L}\p{N}]/u.test(word))
        .length,
    0,
  );
}

export function narrationWordTarget(words: NarrationWords): string {
  if (words.minimum != null && words.maximum != null)
    return words.minimum === words.maximum
      ? `${words.minimum} words`
      : `${words.minimum}–${words.maximum} words`;
  return words.minimum != null
    ? `at least ${words.minimum} words`
    : `at most ${words.maximum} words`;
}

export interface StudioMaterial {
  id: string;
  title: string;
  brief: string;
  creative_project_id: string | null;
  options: StudioOptions;
  version: number;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}
export interface StudioShot {
  purpose: string;
  duration_frames: number;
  visual_kind: "image" | "video" | "library" | "graphics" | "reuse";
  reuse_scene?: number | null;
  visual_brief: string;
  framing: string;
  source_artifact_id: string | null;
  reference_artifact_ids: string[];
  layout: string;
  title: string;
  eyebrow: string;
  body: string;
  points: string[];
  narration: string;
  narration_segments?: { text: string; style: string }[] | null;
  media_motion: string;
  media_fit: "contain" | "cover";
  media_start_seconds: number;
}
export interface Storyboard {
  title: string;
  concept: string;
  hook: string;
  audio: CreativeDefaults["audio"];
  voice_direction: string;
  narration_delivery?: { direction: string; pace: string };
  music_brief: string;
  scenes: StudioShot[];
}
export interface StudioRevision {
  id: string;
  material_id: string;
  parent_revision_id: string | null;
  source_run_id: string | null;
  position: number;
  storyboard: Storyboard;
  sources: Record<string, { kind: string; artifact_id: string }>;
  project_snapshot: {
    name?: string;
    version?: number;
    identity?: { colors: string[] };
  };
  options: StudioOptions;
  brief: string;
  created_at: string;
}
export const materialBase = "/studio/materials";
export const formatNames = {
  reel: "Social reel",
  presentation: "Presentation",
  film: "Film",
};
export const audioNames = {
  voice_music: "Voice + music",
  voice: "Voiceover",
  music: "Music",
  silent: "No audio",
};

export function visualOrigin(scenes: StudioShot[], index: number): number {
  for (let n = 0; n < scenes.length; n++) {
    const shot = scenes[index];
    if (shot?.visual_kind !== "reuse") return index;
    const next = shot.reuse_scene;
    if (next == null || next < 0 || next >= index) return index;
    index = next;
  }
  return index;
}

export function sourceEndSeconds(scenes: StudioShot[], index: number): number {
  const origin = visualOrigin(scenes, index);
  return Math.max(
    ...scenes
      .filter((_, i) => visualOrigin(scenes, i) === origin)
      .map((shot) => shot.duration_frames / 30 + shot.media_start_seconds),
  );
}

export function movedScenes(
  scenes: StudioShot[],
  index: number,
  delta: number,
): StudioShot[] | null {
  const target = index + delta;
  if (target < 0 || target >= scenes.length) return null;
  const order = scenes.map((_, i) => i);
  [order[index], order[target]] = [order[target], order[index]];
  const next = order.map((old) => {
    const shot = scenes[old];
    return shot.visual_kind === "reuse"
      ? { ...shot, reuse_scene: order.indexOf(shot.reuse_scene!) }
      : shot;
  });
  return next.some(
    (s, i) =>
      s.visual_kind === "reuse" &&
      (s.reuse_scene == null || s.reuse_scene >= i),
  )
    ? null
    : next;
}
