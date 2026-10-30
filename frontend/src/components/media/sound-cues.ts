export type SoundCue = {
  start_frame: number;
  end_frame: number;
  prompt: string;
};

export function cuesValid(cues: SoundCue[], frames: number) {
  let previous = 0;
  return cues.every((cue) => {
    const valid =
      Number.isInteger(cue.start_frame) &&
      Number.isInteger(cue.end_frame) &&
      cue.start_frame >= previous &&
      cue.end_frame > cue.start_frame &&
      cue.end_frame <= frames &&
      !!cue.prompt.trim() &&
      cue.prompt.length <= 500;
    previous = cue.end_frame;
    return valid;
  });
}
