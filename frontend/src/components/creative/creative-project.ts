export interface CreativeIdentity {
  colors: string[];
  typography: "sans" | "humanist" | "editorial" | "mono";
  visual_direction: string;
  tone: string;
  audience: string;
  language: string;
  editorial_rules: string;
  audio_direction: string;
}
export interface CreativeDefaults {
  format: "reel" | "presentation" | "film";
  aspect: "portrait" | "landscape" | "square";
  duration_seconds: number;
  audio: "voice_music" | "voice" | "music" | "silent";
}
export interface CreativeProject {
  id: string;
  name: string;
  description: string;
  aliases: string[];
  identity: CreativeIdentity;
  defaults: CreativeDefaults;
  logo_artifact_id: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}
export type CreativeDefinition = Pick<
  CreativeProject,
  | "name"
  | "description"
  | "aliases"
  | "identity"
  | "defaults"
  | "logo_artifact_id"
>;
export const initialDefinition = (): CreativeDefinition => ({
  name: "",
  description: "",
  aliases: [],
  logo_artifact_id: null,
  identity: {
    colors: ["#A8CC74", "#101311", "#F7F8F4"],
    typography: "sans",
    visual_direction: "",
    tone: "",
    audience: "",
    language: "",
    editorial_rules: "",
    audio_direction: "",
  },
  defaults: {
    format: "reel",
    aspect: "portrait",
    duration_seconds: 30,
    audio: "voice_music",
  },
});
export const creativeJson = (method: string, body: unknown) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
