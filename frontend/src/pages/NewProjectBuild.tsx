import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorNotice } from "../components/common";
import {
  CodingModelChoiceList,
  type CodingModelChoice,
} from "./CodingModelChoiceList";

import type { NewProjectScope } from "./new-project-scope";

export function NewProjectBuild({
  value,
  onChange,
  busy,
}: {
  value: NewProjectScope;
  onChange: (scope: NewProjectScope) => void;
  busy?: boolean;
}) {
  const external = value.executor !== "local";
  const models = useQuery({
    queryKey: ["coding-models", value.executor],
    queryFn: () =>
      api<{ models: CodingModelChoice[] }>(`/coding/models/${value.executor}`),
    enabled: external,
  });
  return (
    <section
      className="assistant-coding-scope new-project-build"
      aria-label="New project and coding"
    >
      <label>
        Project name
        <input
          required
          maxLength={200}
          value={value.name}
          disabled={busy}
          placeholder="Weather Station"
          onChange={(event) => onChange({ ...value, name: event.target.value })}
        />
      </label>
      <p className="muted">
        AI Station creates the folder, Git repository and Python environment.
        Describe what to build in your message; coding starts in an isolated
        worktree.
      </p>
      <fieldset disabled={busy}>
        <legend>Coding agent</legend>
        <div className="project-build-agents">
          {(["local", "cursor", "codex"] as const).map((executor) => (
            <label key={executor} className="agent-tool">
              <input
                type="radio"
                name="new-project-agent"
                checked={value.executor === executor}
                onChange={() =>
                  onChange({
                    ...value,
                    executor,
                    external_ai: false,
                    model: "",
                    max_repair_attempts: 0,
                  })
                }
              />
              {executor === "local"
                ? "Local AI"
                : executor === "cursor"
                  ? "Cursor"
                  : "Codex"}
            </label>
          ))}
        </div>
      </fieldset>
      {external ? (
        <>
          <details>
            <summary>
              Model ·{" "}
              {models.data?.models?.find((model) => model.id === value.model)
                ?.name ?? "Auto"}
            </summary>
            <CodingModelChoiceList
              models={models.data?.models ?? []}
              value={value.model}
              disabled={busy}
              onChange={(model) => onChange({ ...value, model })}
            />
          </details>
          <ErrorNotice error={models.error} />
          <label className="agent-tool">
            <input
              type="checkbox"
              checked={value.external_ai}
              disabled={busy}
              onChange={(event) =>
                onChange({ ...value, external_ai: event.target.checked })
              }
            />
            Allow sharing this goal and the new project's source with{" "}
            {value.executor === "cursor" ? "Cursor" : "Codex"}
          </label>
        </>
      ) : (
        <p className="muted">
          Local coding uses the local model selected for this conversation. No
          external AI is used.
        </p>
      )}
    </section>
  );
}
