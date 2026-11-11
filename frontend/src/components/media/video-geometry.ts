import type { VideoCapabilities } from "./VideoMemoryProfile";

export function boundedResolutions(capability?: VideoCapabilities): string[] {
  const portrait = capability?.memory_profiles?.some(
    (profile) =>
      profile.id === "bounded_11g" &&
      profile.available &&
      profile.resolutions?.some(
        (size) => size.width === 704 && size.height === 1280,
      ),
  );
  return portrait ? ["1280x704", "704x1280"] : ["1280x704"];
}
