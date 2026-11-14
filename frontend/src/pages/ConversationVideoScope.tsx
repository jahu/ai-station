import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorNotice } from "../components/common";
import VideoModelChoice from "../components/media/VideoModelChoice";
import VideoMemoryProfile, {
  type VideoCapabilities,
  type VideoProfile,
} from "../components/media/VideoMemoryProfile";
import { recipeResolutions } from "../components/media/video-geometry";

export type ConversationVideoSettings = {
  duration_seconds: number;
  composition_mode: "continuous" | "shots";
  model_id?: string;
  width?: number;
  height?: number;
  memory_profile?: VideoProfile;
};

export default function ConversationVideoScope({
  value,
  disabled,
  onChange,
  onFrameRateChange,
}: {
  value?: ConversationVideoSettings | null;
  disabled: boolean;
  onChange: (value: ConversationVideoSettings | null) => void;
  onFrameRateChange: (fps: number) => void;
}) {
  const capability = useQuery({
    queryKey: ["video-capabilities", value?.model_id],
    enabled: !!value?.model_id,
    queryFn: () =>
      api<VideoCapabilities>(`/video/models/${value?.model_id}/capabilities`),
  });
  const recipe = capability.data?.operation_recipe;
  const formats = recipeResolutions(capability.data);
  const format = `${value?.width ?? recipe?.width}x${value?.height ?? recipe?.height}`;
  const unavailable = !!recipe && !formats.includes(format);
  useEffect(
    () => onFrameRateChange(recipe?.fps ?? 24),
    [recipe?.fps, onFrameRateChange],
  );
  return (
    <section className="agent-media-scope" aria-label="Video settings">
      <VideoModelChoice
        value={value?.model_id ?? ""}
        disabled={disabled}
        onChange={(id, model) => {
          const selected = model?.operation_recipe;
          onChange({
            duration_seconds: value?.duration_seconds ?? 10,
            composition_mode: value?.composition_mode ?? "continuous",
            ...(id ? { model_id: id } : {}),
            ...(selected
              ? {
                  width: selected.width,
                  height: selected.height,
                  memory_profile: "default" as const,
                }
              : {}),
          });
        }}
      />
      <ErrorNotice error={capability.error} />
      <label>
        Video length
        <select
          value={value?.duration_seconds ?? "preview"}
          disabled={disabled}
          onChange={(event) =>
            onChange(
              event.target.value === "preview"
                ? null
                : {
                    ...value,
                    duration_seconds: Number(event.target.value),
                    composition_mode: value?.composition_mode ?? "continuous",
                  },
            )
          }
        >
          <option value="preview" disabled={!!value?.model_id}>
            Short preview · or describe the duration
          </option>
          {[5, 10, 15, 20, 30, 60].map((seconds) => (
            <option key={seconds} value={seconds}>
              {seconds} seconds
            </option>
          ))}
          {value &&
            ![5, 10, 15, 20, 30, 60].includes(value.duration_seconds) && (
              <option value={value.duration_seconds}>
                {value.duration_seconds} seconds
              </option>
            )}
        </select>
      </label>
      {recipe && (
        <label>
          Video format
          <select
            aria-label="Video format"
            value={format}
            disabled={disabled || (formats.length < 2 && !unavailable)}
            onChange={(event) => {
              const [width, height] = event.target.value.split("x").map(Number);
              onChange({ ...value!, width, height });
            }}
          >
            {unavailable && (
              <option disabled value={format}>
                Saved format · {format.replace("x", " × ")} · unavailable
              </option>
            )}
            {formats.map((size) => (
              <option key={size} value={size}>
                {Number(size.split("x")[0]) > Number(size.split("x")[1])
                  ? "Landscape"
                  : "Portrait"}{" "}
                · {size.replace("x", " × ")}
              </option>
            ))}
          </select>
        </label>
      )}
      {unavailable && (
        <p className="notice">
          Choose an available video format before sending.
        </p>
      )}
      {recipe?.image_required && (
        <p className="muted">
          Add one original image. It anchors every continuation of the film.
        </p>
      )}
      {value?.model_id && (
        <VideoMemoryProfile
          value={value.memory_profile ?? "default"}
          modelId={value.model_id}
          disabled={disabled}
          onChange={(memory_profile) => onChange({ ...value, memory_profile })}
        />
      )}
    </section>
  );
}
