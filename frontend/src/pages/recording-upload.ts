import type { QueryClient } from "@tanstack/react-query";
import { api, type Artifact } from "../api";

export function isRecordingFile(file: File) {
  return (
    /^(audio\/(wav|x-wav|wave|mpeg|mp3|mp4|x-m4a|ogg|webm|flac|x-flac)|video\/webm)$/i.test(
      file.type,
    ) || /\.(wav|mp3|m4a|ogg|oga|webm|flac)$/i.test(file.name)
  );
}

export async function uploadRecordingFiles(
  files: File[],
  cache: QueryClient,
  onAdded: (artifact: Artifact) => void,
) {
  if (files.length !== 1) throw new Error("Choose one recording at a time.");
  const file = files[0];
  if (!isRecordingFile(file))
    throw new Error("Choose WAV, MP3, M4A, Ogg, WebM or FLAC audio.");
  if (!file.size || file.size > 20 * 1024 * 1024)
    throw new Error("Choose a non-empty recording up to 20 MiB.");
  const body = new FormData();
  body.append("file", file);
  const artifact = await api<Artifact>("/audio/transcription/uploads", {
    method: "POST",
    body,
  });
  cache.setQueryData(["artifact", artifact.id], artifact);
  onAdded(artifact);
  void cache.invalidateQueries({ queryKey: ["library"] });
  return artifact;
}
