import type { Artifact } from "../api";

export function artifactName(artifact: Artifact) {
  return (
    artifact.title ||
    (artifact.metadata.mode
      ? ({
          t2i: "Generate",
          img2img: "Edit",
          recompose: "Recompose",
          upscale: "Upscale",
        }[artifact.metadata.mode] ?? artifact.metadata.mode)
      : artifact.original_filename)
  );
}
