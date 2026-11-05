import { useQuery } from "@tanstack/react-query";
import { api } from "../../api";
import { useWholeAvatarCapabilities } from "./AvatarWholeProfile";

export default function AvatarModelChoice({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const models = useQuery({
    queryKey: ["avatar-models"],
    queryFn: () =>
      api<{ items?: { id: string; name: string; available: boolean }[] }>(
        "/avatars/models",
      ),
  });
  const selected = useWholeAvatarCapabilities(!!value, value);
  if (!value && !models.data?.items?.length) return null;
  return (
    <label>
      Avatar model
      <select
        aria-label="Avatar model"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
      >
        <option value="">Default · current avatar setup</option>
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
        <small className="muted" role="status">
          {selected.isPending || selected.data?.readiness === "checking"
            ? "Checking the installed model files…"
            : selected.isError
              ? "This model needs attention. Check it in Models before starting."
              : "Animates the complete recording. Your selected model stays with the task."}
        </small>
      )}
    </label>
  );
}
