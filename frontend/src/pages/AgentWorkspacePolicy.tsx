export type WorkspacePolicy = {
  auto_install_dependencies?: boolean;
  auto_validate?: boolean;
};

export default function AgentWorkspacePolicy({
  value,
  linkedProject,
  disabled,
  onChange,
}: {
  value?: WorkspacePolicy;
  linkedProject?: string | null;
  disabled?: boolean;
  onChange: (value: WorkspacePolicy) => void;
}) {
  const current = {
    auto_install_dependencies: value?.auto_install_dependencies === true,
    auto_validate: value?.auto_validate === true,
  };
  return (
    <fieldset
      className="agent-wide agent-workspace-policy"
      disabled={disabled || !!linkedProject}
    >
      <legend>Build and check the result</legend>
      <p className="muted">
        {linkedProject
          ? "This agent uses the linked project's saved dependency and validation policy. These preferences only apply when creating a new private workspace."
          : "AI Station creates the private workspace. Choose what it may do after the agent writes code."}
      </p>
      <label className="project-checkbox">
        <input
          type="checkbox"
          checked={current.auto_install_dependencies}
          onChange={(e) =>
            onChange({
              ...current,
              auto_install_dependencies: e.target.checked,
            })
          }
        />
        Install declared project dependencies
      </label>
      <p className="muted">
        May download declared Python/npm packages from checked public package
        sources.
      </p>
      <label className="project-checkbox">
        <input
          type="checkbox"
          checked={current.auto_validate}
          onChange={(e) =>
            onChange({ ...current, auto_validate: e.target.checked })
          }
        />
        Run detected tests and builds
      </label>
      <p className="muted">
        Successful static website builds appear with downloads and Preview. If
        checks fail, Local coding tries one correction within the same time
        limit. Remaining failures stay in the workspace.
      </p>
    </fieldset>
  );
}
