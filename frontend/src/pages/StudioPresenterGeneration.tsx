import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { UserRound } from "lucide-react";
import { api } from "../api";
import { useAccount } from "../account-context";
import MediaInput from "../components/media/MediaInput";
import { ErrorNotice } from "../components/common";

export type PresenterGeneration = {
  image_artifact_id: string;
  placement: "auto" | "right" | "bottom";
  model_id?: string;
};

export default function StudioPresenterGeneration({
  value,
  onChange,
  onReady,
  onBusy,
  disabled,
  supported,
  narrated,
}: {
  value: PresenterGeneration | null;
  onChange: (value: PresenterGeneration | null) => void;
  onReady: (ready: boolean) => void;
  onBusy: (busy: boolean) => void;
  disabled: boolean;
  supported: boolean;
  narrated: boolean;
}) {
  const [open, setOpen] = useState(false);
  const { user } = useAccount();
  const models = useQuery({
    queryKey: ["studio-presenter-models", user?.id],
    enabled: open || !!value,
    queryFn: ({ signal }) =>
      api<{ items: { id: string; name: string; available: boolean }[] }>(
        "/avatars/models",
        { signal },
      ),
  });
  const capabilities = useQuery({
    queryKey: ["studio-presenter-readiness", user?.id, value?.model_id],
    enabled: !!value && supported && narrated,
    queryFn: ({ signal }) =>
      api<{ available: boolean; readiness?: string; reason?: string }>(
        value?.model_id
          ? `/avatars/models/${value.model_id}/capabilities`
          : "/avatars/whole-capabilities",
        { signal },
      ),
    refetchInterval: (q) =>
      q.state.data?.readiness === "checking" ? 1500 : false,
  });
  useEffect(
    () =>
      onReady(
        !value ||
          (supported && narrated && capabilities.data?.available === true),
      ),
    [value, supported, narrated, capabilities.data?.available, onReady],
  );
  return (
    <details
      className="studio-presenter"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        <UserRound size={17} /> Create a speaking presenter{" "}
        <span>Optional</span>
      </summary>
      <p className="studio-direction-note">
        Choose a portrait and your presenter will speak this film’s narration.
        The story stays visible beside or above them, with one voice and the
        same soundtrack.
      </p>
      {!narrated && (
        <p className="notice">
          Choose narration or narration with music in the story settings to
          create a speaking presenter.
        </p>
      )}
      {!supported && (
        <p className="studio-direction-note">
          Prepare the current Studio renderer to enable automatic presenters.
        </p>
      )}
      <MediaInput
        kind="image"
        label="Presenter portrait"
        uploadLabel="Upload presenter portrait"
        hint="Upload or choose a clear PNG, JPEG or WebP portrait."
        imageTypes={["image/png", "image/jpeg", "image/webp"]}
        value={value?.image_artifact_id ?? ""}
        disabled={disabled}
        onBusy={onBusy}
        onChange={(image) =>
          onChange(
            image
              ? {
                  image_artifact_id: image,
                  placement: value?.placement ?? "auto",
                  ...(value?.model_id ? { model_id: value.model_id } : {}),
                }
              : null,
          )
        }
      />
      {value && (
        <div className="studio-presenter-generation-options">
          <label>
            Presenter position
            <select
              value={value.placement}
              disabled={disabled}
              onChange={(event) =>
                onChange({
                  ...value,
                  placement: event.target
                    .value as PresenterGeneration["placement"],
                })
              }
            >
              <option value="auto">Automatic · fits the film</option>
              <option value="right">Beside the story</option>
              <option value="bottom">Below the story</option>
            </select>
          </label>
          <label>
            Avatar model
            <select
              value={value.model_id ?? ""}
              disabled={disabled || models.isPending}
              onChange={(event) =>
                onChange({
                  ...value,
                  model_id: event.target.value || undefined,
                })
              }
            >
              <option value="">Station avatar model</option>
              {models.data?.items?.map((model) => (
                <option
                  key={model.id}
                  value={model.id}
                  disabled={!model.available}
                >
                  {model.name}
                  {!model.available ? " · unavailable" : ""}
                </option>
              ))}
            </select>
          </label>
          {capabilities.isPending && supported && narrated ? (
            <p className="muted" role="status">
              Checking the local avatar model…
            </p>
          ) : (
            capabilities.data?.available === false && (
              <p className="notice">
                {capabilities.data.reason ||
                  "Prepare an avatar model before production."}{" "}
                <Link to="/models">Open Models ↗</Link>
              </p>
            )
          )}
        </div>
      )}
      <ErrorNotice error={models.error ?? capabilities.error} />
    </details>
  );
}
