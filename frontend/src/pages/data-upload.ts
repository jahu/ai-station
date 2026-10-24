import type { QueryClient } from "@tanstack/react-query";
import { api, type Artifact } from "../api";

export function isDataFile(file: File) {
  return /\.(csv|xlsx|json)$/i.test(file.name);
}

export async function uploadDataFiles(
  selected: File[],
  cache: QueryClient,
  onAdded: (artifacts: Artifact[]) => void,
  existingCount = 0,
  existingBytes = 0,
) {
  if (selected.length + existingCount > 8)
    throw new Error("Choose up to eight data files.");
  if (selected.some((file) => !isDataFile(file)))
    throw new Error("Choose CSV, XLSX or JSON files for local data analysis.");
  if (
    selected.some(
      (file) => /\.json$/i.test(file.name) && file.size > 4 * 1024 * 1024,
    )
  )
    throw new Error("JSON files may be up to 4 MB.");
  if (selected.some((file) => file.size > 16 * 1024 * 1024))
    throw new Error("Each file may be up to 16 MB.");
  if (
    selected.reduce((bytes, file) => bytes + file.size, existingBytes) >
    32 * 1024 * 1024
  )
    throw new Error("Selected data files may total up to 32 MB.");
  const added: Artifact[] = [];
  try {
    for (const file of selected) {
      const body = new FormData();
      body.append("file", file);
      const artifact = await api<Artifact>("/data/uploads", {
        method: "POST",
        body,
      });
      added.push(artifact);
      cache.setQueryData(["artifact", artifact.id], artifact);
    }
  } finally {
    // Publish once, including partial success. An editor may autosave this callback.
    if (added.length) onAdded(added);
    void cache.invalidateQueries({ queryKey: ["library"] });
  }
  return added;
}
