import { expect, it } from "vitest";
import {
  clipFrames,
  endFrame,
  errorFor,
  normalize,
  retime,
  type Source,
} from "./timeline";

it("retains source-frame trims across frame-rate changes and rejects overlapping video", () => {
  const sources: Record<string, Source> = {
    a: { artifact_id: "a", kind: "video", title: "A", fps: 25, frames: 25 },
  };
  const m = normalize({
    fps: 24,
    clips: [
      {
        artifact_id: "a",
        in_frame: 0,
        out_frame: 25,
        start_frame: 24,
        gain: 1,
        muted: false,
        fade_in_frames: 0,
        fade_out_frames: 0,
      },
    ],
    tracks: [],
  });
  expect(clipFrames(m.clips[0], m, sources)).toBe(24);
  expect(endFrame(m, sources)).toBe(48);
  const changed = retime(m, 25);
  expect(changed.clips[0]).toMatchObject({
    in_frame: 0,
    out_frame: 25,
    start_frame: 25,
  });
  expect(endFrame(changed, sources)).toBe(50);
  expect(errorFor(changed, sources)).toBeNull();
  expect(
    errorFor(
      { ...m, clips: [...m.clips, { ...m.clips[0], start_frame: 30 }] },
      sources,
    ),
  ).toContain("overlap");
});

it("preserves a native fifteen-fps project and exact clip duration", () => {
  const m = normalize({
    fps: 15,
    clips: [
      {
        artifact_id: "source",
        in_frame: 0,
        out_frame: 150,
        start_frame: 0,
        gain: 1,
        muted: false,
        fade_in_frames: 0,
        fade_out_frames: 0,
      },
    ],
    tracks: [],
  });
  const sources: Record<string, Source> = {
    source: {
      artifact_id: "source",
      kind: "video",
      title: "SVI clip",
      fps: 15,
      frames: 150,
    },
  };
  expect(m.fps).toBe(15);
  expect(endFrame(m, sources)).toBe(150);
  expect(errorFor(m, sources)).toBeNull();
  const changed = retime(m, 24);
  expect(changed.clips[0].out_frame).toBe(150);
  expect(endFrame(changed, sources)).toBe(240);
});
