import type { QueryClient } from "@tanstack/react-query";
import { api, type Artifact } from "../api";

export function isImageFile(file: File) {
  return (
    /^image\/(png|jpeg|webp)$/i.test(file.type) ||
    /\.(png|jpe?g|webp)$/i.test(file.name)
  );
}

export async function uploadImageFiles(
  selected: File[],
  cache: QueryClient,
  onAdded: (artifacts: Artifact[]) => void,
  limit = 4,
  existingCount = 0,
) {
  if (selected.length + existingCount > limit)
    throw new Error(`Attach up to ${limit} images.`);
  if (selected.some((file) => !isImageFile(file)))
    throw new Error("Choose PNG, JPEG or WebP images.");
  if (selected.some((file) => file.size > 20 * 1024 * 1024))
    throw new Error("Each image must be at most 20 MiB.");
  const added: Artifact[] = [];
  try {
    for (const file of selected) {
      const body = new FormData();
      body.append("file", file);
      const artifact = await api<Artifact>("/images/uploads", {
        method: "POST",
        body,
      });
      added.push(artifact);
      cache.setQueryData(["artifact", artifact.id], artifact);
    }
  } finally {
    if (added.length) onAdded(added);
    void cache.invalidateQueries({ queryKey: ["library"] });
  }
  return added;
}
