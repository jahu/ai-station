import type { MusicScopeOptions } from "./music-scope";

export type ImageMediaRequest = {
  mode: "t2i" | "img2img" | "recompose" | "upscale";
  backend?: "qwen" | "juggernaut";
  prompt?: string;
  edit_prompt?: string;
  input_artifact_ids?: string[];
  width?: number;
  height?: number;
  steps?: number;
  cfg?: number;
  max_side?: number;
  gpu?: string;
  seed?: number | null;
  upscale_result?: boolean;
};
export type AgentMediaScope =
  | {
      kind: "image";
      description_source: "fixed" | "goal";
      request: ImageMediaRequest;
    }
  | {
      kind: "music";
      description_source: "fixed" | "goal";
      request: Omit<MusicScopeOptions, "duration_seconds"> & {
        caption: string;
        duration_seconds: number;
      };
    };

export function newAgentMedia(
  kind: "image" | "music",
  goal: string,
): AgentMediaScope {
  return kind === "image"
    ? {
        kind,
        description_source: "goal",
        request: {
          mode: "t2i",
          backend: "qwen",
          prompt: goal.slice(0, 10000),
          width: 832,
          height: 1216,
          steps: 35,
          cfg: 5,
          gpu: "auto",
        },
      }
    : {
        kind,
        description_source: "goal",
        request: {
          caption: goal.slice(0, 512),
          duration_seconds: 30,
          instrumental: true,
          lyrics: "",
          gpu: "auto",
          seed: null,
        },
      };
}

export function fixedAgentMedia(agent: {
  tools?: string[];
  media?: AgentMediaScope | null;
}) {
  return (
    agent.tools?.length === 1 &&
    agent.tools[0] === "create_media" &&
    agent.media?.description_source === "fixed"
  );
}

export function agentMediaIssue(scope?: AgentMediaScope | null): string | null {
  if (!scope) return "Choose the output and save its creative settings.";
  if (scope.kind === "music") {
    const p = scope.request;
    if (!p.caption.trim() || p.caption.trim().length > 512)
      return "Describe the music in 1–512 characters.";
    if (
      !Number.isInteger(p.duration_seconds) ||
      p.duration_seconds < 10 ||
      p.duration_seconds > 600
    )
      return "Choose a music length from 10 to 600 seconds.";
    if (p.instrumental === false && !p.lyrics?.trim())
      return "Add the lyrics for your song.";
    if ((p.lyrics?.length ?? 0) > 4096)
      return "Keep lyrics within 4096 characters.";
    if (
      p.seed != null &&
      (!Number.isInteger(p.seed) || p.seed < 0 || p.seed > 2147483647)
    )
      return "Choose a whole seed between 0 and 2147483647.";
  } else {
    const p = scope.request;
    if (
      p.mode !== "upscale" &&
      !(p.mode === "img2img" ? p.edit_prompt : p.prompt)?.trim()
    )
      return "Add the creative direction for your image.";
    const ids = p.input_artifact_ids ?? [];
    if (p.mode !== "t2i" && (!ids.length || ids.some((id) => !id)))
      return "Choose the source images from Library or upload them.";
    if (["img2img", "upscale"].includes(p.mode) && ids.length !== 1)
      return "Choose one source image.";
    if (p.mode === "recompose" && ids.length > 8)
      return "Choose at most eight reference images.";
  }
  return null;
}
