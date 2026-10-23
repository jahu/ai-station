import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorNotice } from "../components/common";
import AgentDataFiles from "./AgentDataFiles";
import type { ConversationDataScope } from "./useDataInputs";

export default function ConversationDataControls({
  value,
  disabled,
  onChange,
  onUploading,
}: {
  value?: ConversationDataScope | null;
  disabled: boolean;
  onChange: (scope: ConversationDataScope) => void;
  onUploading: (busy: boolean) => void;
}) {
  const scope = value ?? { input_artifact_ids: [], max_repairs: 1 };
  const catalog = useQuery({
    queryKey: ["llama-models"],
    queryFn: () =>
      api<{ models: { model_key: string; name: string }[] }>("/llama"),
    staleTime: 30000,
  });
  return (
    <section
      className="conversation-data-controls"
      aria-label="Local data analysis"
    >
      <AgentDataFiles
        value={scope}
        disabled={disabled}
        showInspection
        onUploading={onUploading}
        onChange={(files) => onChange({ ...scope, ...files })}
      />
      <details>
        <summary>Analysis settings</summary>
        <label>
          Local analysis model
          <select
            value={scope.model ?? "auto"}
            disabled={disabled}
            onChange={(event) =>
              onChange({ ...scope, model: event.target.value })
            }
          >
            <option value="auto">Auto · choose a fitting local model</option>
            {(catalog.data?.models ?? [])
              .filter((model) => model.model_key.startsWith("llamacpp:"))
              .map((model) => (
                <option value={model.model_key} key={model.model_key}>
                  {model.name}
                </option>
              ))}
          </select>
        </label>
        <ErrorNotice error={catalog.error} />
        <label>
          Time limit
          <select
            value={scope.maximum_runtime ?? 600}
            disabled={disabled}
            onChange={(event) =>
              onChange({
                ...scope,
                maximum_runtime: Number(event.target.value),
              })
            }
          >
            <option value={300}>5 minutes</option>
            <option value={600}>10 minutes</option>
            <option value={1800}>30 minutes</option>
            <option value={3600}>60 minutes</option>
          </select>
        </label>
      </details>
      <p className="muted">
        Your files stay on this station, even if the conversation uses an
        external model. Analysis may load a local model automatically.
      </p>
    </section>
  );
}
