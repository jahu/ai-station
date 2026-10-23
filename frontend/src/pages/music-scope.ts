export type MusicScopeOptions = {
  duration_seconds?: number | null;
  instrumental?: boolean;
  lyrics?: string;
  seed?: number | null;
  gpu?: string;
};

export type ConversationMusicOptions = MusicScopeOptions & {
  lyrics_source?: "fixed" | "goal";
};

export function musicScopeReady(
  options: { action: string; music?: ConversationMusicOptions | null },
  description: string,
) {
  if (options.action !== "audio.music") return options.music == null;
  const scope = options.music ?? {};
  return (
    !!description.trim() &&
    description.trim().length <=
      (scope.lyrics_source === "goal" ? 16000 : 512) &&
    (scope.lyrics_source !== "goal" || scope.instrumental === false) &&
    (scope.instrumental !== false ||
      scope.lyrics_source === "goal" ||
      !!scope.lyrics?.trim()) &&
    (scope.lyrics?.length ?? 0) <= 4096 &&
    (scope.duration_seconds == null ||
      (Number.isInteger(scope.duration_seconds) &&
        scope.duration_seconds >= 10 &&
        scope.duration_seconds <= 600)) &&
    (scope.seed == null ||
      (Number.isInteger(scope.seed) &&
        scope.seed >= 0 &&
        scope.seed <= 2147483647))
  );
}
