import type { AssistantOptions } from "./AssistantActions";

export const emptyOptions: AssistantOptions = {
  action: "auto",
  image_artifact_ids: [],
  audio_artifact_id: null,
  coding: null,
  new_project: null,
  commit: null,
  publish: null,
  load: null,
  stop: null,
};
