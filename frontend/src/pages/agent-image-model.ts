import type { ImageMediaRequest } from "./agent-media";
import { imageSettings, type ImageModel } from "./image-models";

export function changeAgentImageModel(
  request: ImageMediaRequest,
  model: ImageModel,
): ImageMediaRequest {
  if (
    !model.available ||
    !model.modes.includes(request.mode) ||
    (request.input_artifact_ids?.filter(Boolean).length ?? 0) >
      model.maximum_references
  ) {
    return request;
  }
  const next: ImageMediaRequest = {
    ...request,
    ...imageSettings(model, request.mode),
    backend: model.backend,
  };
  delete next.model_id;
  delete next.model_selection;
  delete next.model_selection_revision;
  if (model.definition_id) next.model_id = model.definition_id;
  if (model.backend !== "krea2" || request.mode === "t2i") {
    delete next.reference_strength;
    delete next.reference_layout;
    delete next.grounding_px;
  } else if (!model.presets?.[request.mode]?.reference_layout) {
    next.reference_layout = request.mode === "recompose" ? "beside" : "aligned";
  }
  if (model.backend === "qwen") {
    next.seed = null;
  }
  if (model.backend !== "juggernaut") {
    next.negative = null;
  }
  return next;
}
