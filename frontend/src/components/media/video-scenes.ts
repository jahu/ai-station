export type SceneDraft = {
  key: string;
  prompt: string;
  duration_seconds: number;
};

export function scenePlanError(shared: string, scenes: SceneDraft[]) {
  if (!scenes.length || scenes.some((scene) => !scene.prompt.trim()))
    return "Describe every scene before generating.";
  if (
    scenes.some(
      (scene) =>
        !Number.isInteger(scene.duration_seconds) ||
        scene.duration_seconds < 1 ||
        scene.duration_seconds > 60,
    )
  )
    return "Each scene needs a duration from 1 to 60 whole seconds.";
  if (scenes.reduce((total, scene) => total + scene.duration_seconds, 0) > 60)
    return "The complete film can be up to 60 seconds.";
  if (
    scenes.some(
      (scene) => shared.trim().length + 2 + scene.prompt.trim().length > 2000,
    )
  )
    return "Shared instructions and each scene must fit 2000 characters together.";
  return "";
}
