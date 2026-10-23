export type MusicScopeOptions = {
  duration_seconds?: number | null;
  instrumental?: boolean;
  lyrics?: string;
  seed?: number | null;
  gpu?: string;
};

export function musicScopeReady(
  options: { action: string; music?: MusicScopeOptions | null },
  description: string,
) {
  if (options.action !== "audio.music") return options.music == null;
  const scope = options.music ?? {};
  return (
    !!description.trim() &&
    description.trim().length <= 512 &&
    (scope.instrumental !== false || !!scope.lyrics?.trim()) &&
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
