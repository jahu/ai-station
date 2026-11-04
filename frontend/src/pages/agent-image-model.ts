import type { ImageMediaRequest } from "./agent-media";

export function changeAgentImageModel(
  request: ImageMediaRequest,
  backend: "qwen" | "juggernaut",
): ImageMediaRequest {
  const next = { ...request, backend };
  delete next.model_id;
  delete next.model_selection;
  delete next.model_selection_revision;
  delete next.reference_strength;
  delete next.reference_layout;
  delete next.grounding_px;
  if (backend === "qwen") {
    next.seed = null;
    next.negative = null;
  }
  return next;
}
