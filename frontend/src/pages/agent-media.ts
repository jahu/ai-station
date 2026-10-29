import type { MusicScopeOptions } from "./music-scope";
import {
  WHOLE_AVATAR_PROFILE,
  type AvatarGenerationProfile,
} from "../components/media/AvatarWholeProfile";

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
export type VideoMediaRequest = {
  memory_profile?: "default" | "bounded_11g";
  prompt: string;
  negative_prompt?: string;
  image_artifact_id?: string | null;
  duration_seconds: number;
  composition_mode: "continuous" | "shots";
  scenes?: { prompt: string; duration_seconds: number }[] | null;
  width?: number;
  height?: number;
  steps?: number;
  cfg?: number;
  seed?: number;
  gpu?: string;
};
export type AvatarMediaRequest = {
  generation_profile?: AvatarGenerationProfile;
  memory_profile?: "default" | "bounded_11g";
  image_artifact_id: string | null;
  audio_artifact_id: string | null;
  speech_text: string | null;
  prompt: string;
  size?: 256 | 384 | 512;
  steps?: number;
  seed?: number;
  gpu?: string;
};
export type AgentMediaScope =
  | {
      kind: "avatar";
      description_source: "fixed" | "goal";
      request: AvatarMediaRequest;
    }
  | {
      kind: "video";
      description_source: "fixed" | "goal";
      request: VideoMediaRequest;
    }
  | {
      kind: "speech";
      description_source: "fixed" | "goal";
      request: {
        text: string;
        reference_artifact_id: string | null;
        gpu?: string;
      };
    }
  | {
      kind: "image";
      description_source: "fixed" | "goal";
      request: ImageMediaRequest;
    }
  | {
      kind: "music";
      description_source: "fixed" | "goal";
      lyrics_source?: "fixed" | "goal";
      request: Omit<MusicScopeOptions, "duration_seconds"> & {
        caption: string;
        duration_seconds: number;
      };
    };

export function newAgentMedia(
  kind: AgentMediaScope["kind"],
  goal: string,
  wholeAvatar = false,
): AgentMediaScope {
  if (kind === "avatar")
    return {
      kind,
      description_source: "goal",
      request: {
        image_artifact_id: null,
        audio_artifact_id: null,
        speech_text: goal.slice(0, 1000),
        prompt: "A person speaking naturally, static camera.",
        ...(wholeAvatar
          ? { generation_profile: WHOLE_AVATAR_PROFILE }
          : { size: 384, steps: 8 }),
        seed: 43,
        gpu: "auto",
      },
    };
  if (kind === "video")
    return {
      kind,
      description_source: "goal",
      request: {
        prompt: goal.slice(0, 2000),
        duration_seconds: 15,
        composition_mode: "continuous",
        image_artifact_id: null,
        width: 1280,
        height: 704,
        steps: 20,
        cfg: 5,
        seed: 43,
        gpu: "auto",
      },
    };
  if (kind === "speech")
    return {
      kind,
      description_source: "goal",
      request: {
        text: goal.slice(0, 1000),
        reference_artifact_id: null,
        gpu: "auto",
      },
    };
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

export function stableAvatarRequest(
  value: AvatarMediaRequest,
): AvatarMediaRequest {
  const request = { ...value, generation_profile: WHOLE_AVATAR_PROFILE };
  delete request.size;
  delete request.steps;
  delete request.memory_profile;
  return request;
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

export function agentMediaIssue(
  scope?: AgentMediaScope | null,
  options?: { allowMissingVoice?: boolean; allowMissingSources?: boolean },
): string | null {
  if (!scope) return "Choose the output and save its creative settings.";
  if (scope.kind === "avatar") {
    const p = scope.request;
    if (
      p.generation_profile &&
      (p.size !== undefined ||
        p.steps !== undefined ||
        p.memory_profile === "bounded_11g")
    )
      return "Use the stable-detail setup without legacy resolution or step controls.";
    if (
      p.generation_profile &&
      p.speech_text === null &&
      scope.description_source === "goal"
    )
      return "Use fixed recording mode, or type words for a fresh spoken briefing.";
    if (
      p.memory_profile === "bounded_11g" &&
      ((p.size ?? 384) !== 384 || (p.steps ?? 8) < 8)
    )
      return "Use 384 × 384 with at least 8 steps for Reduced RAM, or choose Standard.";
    if (
      (!p.image_artifact_id || !p.audio_artifact_id) &&
      !options?.allowMissingSources
    )
      return "Choose a portrait and a WAV voice or recording before enabling.";
    if (
      p.speech_text !== null &&
      (!p.speech_text.trim() || p.speech_text.length > 1000)
    )
      return "Write the Polish words or instructions in 1–1000 characters.";
    if (!p.prompt.trim() || p.prompt.length > 2000)
      return "Describe the avatar motion in 1–2000 characters.";
    return null;
  }
  if (scope.kind === "video") {
    const p = scope.request;
    if (!p.prompt.trim() || p.prompt.length > 2000)
      return "Describe the video in 1–2000 characters.";
    if (
      !Number.isInteger(p.duration_seconds) ||
      p.duration_seconds < 1 ||
      p.duration_seconds > 60
    )
      return "Choose a film length from 1 to 60 whole seconds.";
    if (
      p.scenes?.length &&
      (p.composition_mode !== "shots" ||
        p.scenes.length > 20 ||
        p.scenes.some(
          (scene) =>
            !scene.prompt.trim() ||
            scene.prompt.length > 1000 ||
            !Number.isInteger(scene.duration_seconds) ||
            scene.duration_seconds < 1 ||
            scene.duration_seconds > 60 ||
            p.prompt.trim().length + 2 + scene.prompt.trim().length > 2000,
        ) ||
        p.scenes.reduce((sum, scene) => sum + scene.duration_seconds, 0) !==
          p.duration_seconds)
    )
      return "Describe each shot and make its lengths add up to the full film.";
    return null;
  }
  if (scope.kind === "speech") {
    if (!scope.request.text.trim() || scope.request.text.length > 1000)
      return "Write the spoken text or instructions in 1–1000 characters.";
    if (!scope.request.reference_artifact_id && !options?.allowMissingVoice)
      return "Choose a voice reference from Library or upload a WAV before enabling.";
    return null;
  }
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
    if (
      scope.lyrics_source === "goal" &&
      (p.instrumental !== false || scope.description_source !== "goal")
    )
      return "Generated lyrics require vocals and a goal-based description.";
    if (
      p.instrumental === false &&
      scope.lyrics_source !== "goal" &&
      !p.lyrics?.trim()
    )
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
    if (p.mode === "upscale" && scope.description_source !== "fixed")
      return "Upscale uses its exact source image without a generated description.";
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
