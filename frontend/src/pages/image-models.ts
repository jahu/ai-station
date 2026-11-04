import type { ImageOperation } from "./ImageOperationChoiceList";

export type ImageSettings = {
  width: number;
  height: number;
  steps: number;
  cfg: number;
  seed: number;
  max_side: number;
  reference_strength: number;
  reference_layout: "aligned" | "beside";
  grounding_px: number;
};
export type ImageModel = {
  id: string;
  definition_id: string | null;
  name: string;
  backend: "qwen" | "juggernaut" | "krea2";
  modes: ImageOperation[];
  available: boolean;
  maximum_references: number;
  gpu_count?: number;
  presets?: Partial<Record<ImageOperation, Partial<ImageSettings>>>;
  license_url?: string;
  file?: { filename: string; format: string; size_bytes: number };
};
export type ImageModelDefaults = {
  revision: number;
  choices: Record<ImageOperation, string>;
};
export type ImageRecommendation = {
  policy: string;
  revision: number;
  reason: string;
  choice: ImageModel;
};

export function recommendationReason(reason: string) {
  if (reason === "pose")
    return "Qwen is recommended for changes to pose, position or orientation.";
  if (reason === "object_removal")
    return "Qwen is recommended for removing an object from the source image.";
  if (reason === "reference_capacity")
    return "Qwen can use all of your selected references.";
  return "Uses your configured model for this kind of edit.";
}
export type ImageModelCatalog = {
  items: ImageModel[];
  defaults: ImageModelDefaults;
};

export function imageSettings(
  model: ImageModel | undefined,
  mode: ImageOperation,
): ImageSettings {
  const krea = model?.backend === "krea2";
  return {
    width: krea ? 768 : 832,
    height: krea ? 1024 : 1216,
    steps: krea ? 8 : mode === "t2i" ? 35 : 30,
    cfg: krea ? 1 : mode === "recompose" ? 6 : 5,
    seed: 42,
    max_side: krea ? 1024 : 1216,
    reference_strength: mode === "img2img" ? 4 : 2,
    reference_layout: "aligned",
    grounding_px: 768,
    ...model?.presets?.[mode],
  };
}
