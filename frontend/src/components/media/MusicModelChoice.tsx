import { useQuery } from "@tanstack/react-query";
import { api } from "../../api";

export default function MusicModelChoice({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const models = useQuery({
    queryKey: ["music-models"],
    queryFn: () =>
      api<{ items?: { id: string; name: string; available: boolean }[] }>(
        "/audio/music/models",
      ),
  });
  if (!value && !models.data?.items?.length) return null;
  return (
    <label>
      Music model
      <select
        aria-label="Music model"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
      >
        <option value="">Default · current music setup</option>
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
          Installed ACE-Step profile · one 12 GiB GPU and at least 24 GiB system
          RAM. Uses explicit CPU offload, with no swap. Your selected model
          stays with the task.
        </small>
      )}
    </label>
  );
}
