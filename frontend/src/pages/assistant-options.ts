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

export function acceptsLocalAttachments(options: AssistantOptions) {
  return (
    ["auto", "chat"].includes(options.action) &&
    !options.image_artifact_ids.length &&
    !options.audio_artifact_id &&
    !options.data &&
    !options.github &&
    !options.coding &&
    !options.new_project &&
    !options.commit &&
    !options.publish &&
    !options.load &&
    !options.stop &&
    !options.music &&
    !options.media &&
    !options.upscale_result &&
    !options.speech_text
  );
}
