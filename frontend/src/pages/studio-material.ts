import type { CreativeDefaults } from "../components/creative/creative-project";

export interface StudioMaterial {
  id: string;
  title: string;
  brief: string;
  creative_project_id: string | null;
  options: CreativeDefaults;
  version: number;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}
export interface StudioShot {
  purpose: string;
  duration_frames: number;
  visual_kind: "image" | "video" | "library" | "graphics";
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
  options: CreativeDefaults;
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
