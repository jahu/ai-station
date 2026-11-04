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
  const result = changeAgentImageModel(original, "qwen");
  expect(result).toEqual({
    mode: "t2i",
    backend: "qwen",
    prompt: "Mountains",
    seed: null,
    negative: null,
    width: 832,
    height: 1216,
  });
  expect(original.negative).toBe("blur");
});
