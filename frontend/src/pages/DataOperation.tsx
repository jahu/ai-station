import type { DataScope } from "./AgentDataFiles";

export default function DataOperation({
  value,
  disabled,
  hasResearch = false,
  hasMemory = false,
  hasDocuments = false,
  onChange,
}: {
  value?: DataScope | null;
  disabled: boolean;
  hasResearch?: boolean;
  hasMemory?: boolean;
  hasDocuments?: boolean;
  onChange: (value: DataScope) => void;
}) {
  const scope = value ?? { input_artifact_ids: [], max_repairs: 1 };
  const hasInputs = scope.input_artifact_ids.length > 0 || hasResearch;
  return (
    <div>
      <label>
        Task
        <select
          aria-label="Data operation"
          disabled={disabled}
          value={scope.operation ?? "analyze"}
          onChange={(event) => {
            if (event.target.value === "create" && hasInputs) return;
            onChange({
              ...scope,
              operation: event.target.value === "create" ? "create" : undefined,
            });
          }}
        >
          <option value="analyze">
            {hasDocuments
              ? "Analyze files or selected documents"
              : hasMemory
                ? "Analyze files or saved observations"
                : "Analyze files or public sources"}
          </option>
          <option value="create" disabled={hasInputs}>
            Create files from instructions
          </option>
        </select>
      </label>
      {hasInputs && (
        <p className="muted">
          To create from instructions alone, first remove selected files and
          {hasMemory || hasDocuments ? "selected context" : "public sources"}.
          Analysis can also create output files.
        </p>
      )}
    </div>
  );
}
