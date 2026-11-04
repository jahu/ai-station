import "./ImageModelSelection.css";
import type { Run } from "../../api";
import {
  recommendationReason,
  type ImageRecommendation,
} from "../../pages/image-models";

export default function ImageModelSelection({ run }: { run?: Run }) {
  const selection = run?.metadata?.image_model_selection as
    ImageRecommendation | undefined;
  if (!selection) return null;
  return (
    <div className="image-model-guidance" aria-label="Image model selection">
      <strong>Auto selected {selection.choice.name}</strong>
      <p className="muted">{recommendationReason(selection.reason)}</p>
    </div>
  );
}
