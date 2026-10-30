import { createContext, useContext, useEffect } from "react";
import type { Artifact, Run } from "../../api";
import type { MediaJob } from "../media/media-job";

export type CreativeCapability =
  "images" | "video" | "music" | "speech" | "avatars";
export type CreativeDraft = Record<string, unknown>;
export interface CreativeSession {
  id: string;
  capability: CreativeCapability;
  title: string;
  draft: CreativeDraft;
  version: number;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}
export interface CreativeTurn {
  id: string;
  position: number;
  parent_turn_id: string | null;
  task_id: string;
  run_id: string;
  parameters: CreativeDraft;
  feedback: string;
  created_at: string;
  run: Run | null;
  runs?: Run[];
  status?: string;
  error_message?: string;
  artifacts: Artifact[];
  request_kind?: "direct" | "job";
  job?: MediaJob | null;
}
export interface CreativeDetail extends CreativeSession {
  turns: CreativeTurn[];
  next_before: number | null;
}
export interface CreativeController {
  id: string;
  formKey: string;
  draft: CreativeDraft;
  setDraft: (value: CreativeDraft) => void;
  generate: (
    parameters: CreativeDraft,
    options?: { kind?: "direct" | "job"; feedback?: string },
  ) => Promise<CreativeTurn>;
}
export const CreativeContext = createContext<CreativeController | null>(null);
export const useCreative = () => useContext(CreativeContext);

export function creativeRun(turn: CreativeTurn): Run {
  if (!turn.run)
    throw new Error(
      "Generation was queued. Refresh this workspace to inspect it.",
    );
  return turn.run;
}
export function creativeJob(turn: CreativeTurn): MediaJob {
  if (!turn.job)
    throw new Error(
      "The media job was queued. Refresh this workspace to inspect it.",
    );
  return turn.job;
}

export function useCreativeDraft(value: CreativeDraft) {
  const update = useCreative()?.setDraft;
  const serialized = JSON.stringify(value);
  useEffect(() => {
    update?.(JSON.parse(serialized) as CreativeDraft);
  }, [serialized, update]);
}
