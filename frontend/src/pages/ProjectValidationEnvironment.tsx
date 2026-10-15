export interface ValidationEnvironment {
  python_manifest:
    | "requirements.txt"
    | "pyproject.toml"
    | "requirements.lock"
    | "requirements-dev.lock"
    | null;
  node_directory: string | null;
  python_source_roots: string[];
  timeout_seconds: number;
}

export function ProjectValidationEnvironment({
  value,
  onChange,
}: {
  value: ValidationEnvironment | null;
  onChange: (value: ValidationEnvironment | null) => void;
}) {
  return (
    <details>
      <summary>Validation environment</summary>
      <div className="project-form-section">
        <p className="muted">
          For repositories with separate application folders or development
          dependencies. Paths are relative to the isolated worktree. Existing
          projects can keep automatic detection.
        </p>
        <label className="agent-tool">
          <input
            type="checkbox"
            checked={value !== null}
            onChange={(event) =>
              onChange(
                event.target.checked
                  ? {
                      python_manifest: null,
                      node_directory: null,
                      python_source_roots: [],
                      timeout_seconds: 900,
                    }
                  : null,
              )
            }
          />
          Use a custom validation environment
        </label>
        {value && (
          <>
            <label>
              Python dependency manifest
              <select
                value={value.python_manifest ?? ""}
                onChange={(event) =>
                  onChange({
                    ...value,
                    python_manifest:
                      (event.target
                        .value as ValidationEnvironment["python_manifest"]) ||
                      null,
                  })
                }
              >
                <option value="">Detect automatically</option>
                {[
                  "requirements.txt",
                  "pyproject.toml",
                  "requirements.lock",
                  "requirements-dev.lock",
                ].map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Frontend package folder
              <input
                value={value.node_directory ?? ""}
                maxLength={300}
                placeholder="frontend"
                onChange={(event) =>
                  onChange({
                    ...value,
                    node_directory: event.target.value || null,
                  })
                }
              />
            </label>
            <p className="muted">
              Leave empty for the repository root. The folder must contain
              package.json. Saved commands can use npm --prefix=frontend.
            </p>
            <label>
              Python source folders (comma separated)
              <input
                value={value.python_source_roots.join(", ")}
                placeholder="backend, host-runner"
                maxLength={3020}
                onChange={(event) =>
                  onChange({
                    ...value,
                    python_source_roots: event.target.value
                      .split(",")
                      .map((path) => path.trim()),
                  })
                }
              />
            </label>
            <label>
              Validation time limit (minutes)
              <input
                type="number"
                min={1}
                max={120}
                required
                value={value.timeout_seconds / 60}
                onChange={(event) =>
                  onChange({
                    ...value,
                    timeout_seconds: Number(event.target.value) * 60,
                  })
                }
              />
            </label>
            <p className="muted">
              Applies to each command and the whole validation Run. Dependencies
              require the separate package preparation option above. Network
              access remains disabled during checks.
            </p>
          </>
        )}
      </div>
    </details>
  );
}
