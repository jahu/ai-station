import { useQuery } from "@tanstack/react-query";
import { api } from "../../api";
import type { VideoCapabilities } from "./VideoMemoryProfile";

type VideoChoice = {
  id: string;
  name: string;
  available: boolean;
  profile?: string;
  operation_recipe?: VideoCapabilities["operation_recipe"];
};

export default function VideoModelChoice({
  value,
  onChange,
  disabled,
  defaultLabel = "Default · current video setup",
}: {
  value: string;
  onChange: (value: string, model?: VideoChoice) => void;
  disabled?: boolean;
  defaultLabel?: string;
}) {
  const models = useQuery({
    queryKey: ["video-models"],
    queryFn: () =>
      api<{
        items?: VideoChoice[];
      }>("/video/models"),
  });
  if (!value && !models.data?.items?.length) return null;
  return (
    <label>
      Video model
      <select
        aria-label="Video model"
        value={value}
        onChange={(event) =>
          onChange(
            event.target.value,
            models.data?.items?.find((item) => item.id === event.target.value),
          )
        }
        disabled={disabled}
      >
        <option value="">{defaultLabel}</option>
        {value && !models.data?.items?.some((model) => model.id === value) && (
          <option value={value} disabled>
            Saved model · unavailable
          </option>
        )}
        {(models.data?.items ?? []).map((model) => (
          <option key={model.id} value={model.id} disabled={!model.available}>
            {model.name}
            {model.available ? "" : " · unavailable"}
          </option>
        ))}
      </select>
      {value && (
        <small className="muted">
          {models.data?.items?.find((model) => model.id === value)?.profile ??
            "Check the selected model's profile before generating."}{" "}
          Uses explicit CPU offload and no swap; the selected model stays with
          every clip of a film.
        </small>
      )}
    </label>
  );
}
