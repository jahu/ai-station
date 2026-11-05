import { useQuery } from "@tanstack/react-query";
import { api } from "../../api";

export default function VideoModelChoice({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const models = useQuery({
    queryKey: ["video-models"],
    queryFn: () =>
      api<{ items?: { id: string; name: string; available: boolean }[] }>(
        "/video/models",
      ),
  });
  if (!value && !models.data?.items?.length) return null;
  return (
    <label>
      Video model
      <select
        aria-label="Video model"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
      >
        <option value="">Default · current video setup</option>
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
          Installed Wan profile · 1280 × 704 · at least 24 GiB system RAM. Uses
          explicit CPU offload and no swap; the selected model stays with every
          clip of a film.
        </small>
      )}
    </label>
  );
}
