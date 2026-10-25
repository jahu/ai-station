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
