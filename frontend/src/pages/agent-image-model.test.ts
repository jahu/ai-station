import { expect, it } from "vitest";
import { changeAgentImageModel } from "./agent-image-model";

it("changes backend without retaining hidden Juggernaut or stale model-specific settings", () => {
  const original = {
    mode: "t2i" as const,
    backend: "juggernaut" as const,
    prompt: "Mountains",
    seed: 71,
    negative: "blur",
    model_id: "old-model",
    reference_strength: 3,
    width: 832,
    height: 1216,
  };
  const result = changeAgentImageModel(original, {
    id: "qwen",
    definition_id: null,
    name: "Qwen",
    backend: "qwen",
    modes: ["t2i", "img2img", "recompose"],
    available: true,
    maximum_references: 8,
  });
  expect(result).toMatchObject({
    mode: "t2i",
    backend: "qwen",
    prompt: "Mountains",
    seed: null,
    negative: null,
    width: 832,
    height: 1216,
  });
  expect(result).not.toHaveProperty("model_id");
  expect(result).not.toHaveProperty("reference_strength");
  expect(original.negative).toBe("blur");
});
