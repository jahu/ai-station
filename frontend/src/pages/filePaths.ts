export function parseFilePaths(value: string) {
  return [
    ...new Set(
      value
        .split("\n")
        .map((path) => path.trim())
        .filter(Boolean),
    ),
  ].slice(0, 10);
}
