import { expect, it } from "vitest";
import {
  movedScenes,
  sourceEndSeconds,
  visualOrigin,
  type StudioShot,
} from "./studio-material";

function shot(purpose: string, reuse_scene?: number): StudioShot {
  return {
    purpose,
    duration_frames: 60,
    visual_kind: reuse_scene == null ? "video" : "reuse",
    reuse_scene,
    visual_brief: "An abstract subject",
    framing: "Macro",
    source_artifact_id: null,
    reference_artifact_ids: [],
    layout: "full_bleed",
    title: purpose,
    eyebrow: "",
    body: "",
    points: [],
    narration: "",
    media_motion: "auto",
    media_fit: "cover",
    media_start_seconds: 0,
  };
}
it("keeps the same visual identity when an unrelated scene moves around a sharing chain", () => {
  const original = [
    shot("A"),
    shot("B"),
    shot("A again", 0),
    shot("A last", 2),
  ];
  const moved = movedScenes(original, 0, 1)!;
  expect(moved.map((s) => s.purpose)).toEqual(["B", "A", "A again", "A last"]);
  expect(moved[2].reuse_scene).toBe(1);
  expect(visualOrigin(moved, 3)).toBe(1);
  expect(original[2].reuse_scene).toBe(0);
  expect(movedScenes(moved, 1, 1)).toBeNull();
  expect(movedScenes(original, 0, -1)).toBeNull();
});
it("budgets the full clip window across direct and chained shared scenes", () => {
  const scenes = [
    shot("Source"),
    { ...shot("Later", 0), duration_frames: 120, media_start_seconds: 4 },
    shot("Last", 1),
    shot("Unrelated"),
  ];
  expect(sourceEndSeconds(scenes, 0)).toBe(8);
  expect(sourceEndSeconds(scenes, 2)).toBe(8);
  expect(sourceEndSeconds(scenes, 3)).toBe(2);
});
