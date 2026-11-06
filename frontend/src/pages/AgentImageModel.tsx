import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import type { ImageMediaRequest } from "./agent-media";
import { changeAgentImageModel } from "./agent-image-model";
import type { ImageModelCatalog } from "./image-models";

export default function AgentImageModel({
  request,
  disabled,
  onChange,
}: {
  request: ImageMediaRequest;
  disabled: boolean;
  onChange: (request: ImageMediaRequest) => void;
}) {
  const catalog = useQuery({
    queryKey: ["image-models"],
    queryFn: () => api<ImageModelCatalog>("/images/models"),
  });
  const choices = (catalog.data?.items ?? []).filter((model) =>
    model.modes.includes(request.mode),
  );
  const references = request.input_artifact_ids?.filter(Boolean).length ?? 0;
  const selected =
    request.model_selection === "auto"
      ? "auto"
      : request.model_id
        ? (choices.find((model) => model.definition_id === request.model_id)
            ?.id ?? request.model_id)
        : (request.backend ?? "qwen");
  const current = choices.find((model) => model.id === selected);
  return (
    <label>
      Image model
      <select
        aria-label="Agent image model"
        value={selected}
        disabled={
          disabled || catalog.isPending || catalog.isError || !choices.length
        }
        onChange={(event) => {
          const model = choices.find((item) => item.id === event.target.value);
          if (model && !disabled && !catalog.isPending && !catalog.isError)
            onChange(changeAgentImageModel(request, model));
        }}
      >
        {!current && (
          <option value={selected} disabled>
            {catalog.isPending
              ? "Loading saved model…"
              : selected === "auto"
                ? "Automatic selection (saved)"
                : "Saved model unavailable — choose a replacement"}
          </option>
        )}
        {choices.map((model) => (
          <option
            key={model.id}
            value={model.id}
            disabled={!model.available || references > model.maximum_references}
          >
            {model.name}
            {!model.available
              ? " · unavailable"
              : references > model.maximum_references
                ? ` · supports at most ${model.maximum_references} references`
                : ""}
          </option>
        ))}
      </select>
      {catalog.isError ? (
        <span role="alert">
          Could not load image models. Your saved choice is unchanged.{" "}
          <button type="button" onClick={() => void catalog.refetch()}>
            Retry
          </button>
        </span>
      ) : (
        <small>
          {current && !current.available
            ? "This saved model is unavailable. Choose an available replacement before running."
            : "Changing model applies its recommended settings and keeps your brief and reference images."}
        </small>
      )}
    </label>
  );
}
