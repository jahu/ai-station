import { useId, type KeyboardEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";
import { useListKeyboard } from "./useListKeyboard";

type Skill = {
  id: string;
  name: string;
  version: string;
  description: string;
  required_permissions: string[];
  instructions: string;
};

const MAX_SKILLS = 4;

function isSkillList(value: unknown): value is Skill[] {
  return (
    Array.isArray(value) &&
    value.every(
      (item) =>
        item &&
        typeof item === "object" &&
        typeof item.id === "string" &&
        typeof item.name === "string" &&
        typeof item.instructions === "string",
    )
  );
}

function placeholderSkill(id: string): Skill {
  return {
    id,
    name: id,
    version: "",
    description: "",
    required_permissions: [],
    instructions: "",
  };
}

export function AgentAttachedSkills({
  ids,
  agentId,
  tabIndex = 0,
  disabled = false,
  pending = false,
  onRemove,
  onAdd,
}: {
  ids: string[];
  agentId?: string;
  tabIndex?: number;
  disabled?: boolean;
  pending?: boolean;
  onRemove?: (id: string) => void;
  onAdd?: (id: string) => void;
}) {
  const labelId = useId();
  const catalog = useQuery({
    queryKey: ["skills"],
    enabled: ids.length > 0 || !!onAdd,
    queryFn: () => api<Skill[]>("/skills"),
  });
  const installed = isSkillList(catalog.data) ? catalog.data : [];
  const byId = new Map(installed.map((skill) => [skill.id, skill]));
  const catalogReady = isSkillList(catalog.data);
  const attached = ids.map((id) => byId.get(id) ?? placeholderSkill(id));
  const extras =
    catalogReady && onAdd
      ? installed.filter((skill) => !ids.includes(skill.id))
      : [];
  const rows = [...attached, ...extras];
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    rows,
    (skill) => skill.id,
  );
  const active = tabIndex >= 0;
  const shortId = agentId?.slice(0, 8) ?? "";
  const atLimit = ids.length >= MAX_SKILLS;
  const addable = (skill: Skill) =>
    !!onAdd && catalogReady && byId.has(skill.id) && !atLimit;
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown(event);
    if (event.key !== "Enter" && event.key !== " ") return;
    const target = event.target as HTMLElement;
    if (target.closest("a, button, textarea, input, summary, select")) return;
    event.preventDefault();
    const skill = rows[index];
    if (!skill || ids.includes(skill.id) || !addable(skill)) return;
    if (disabled || pending) return;
    onAdd?.(skill.id);
  };
  if (!rows.length) {
    if (!onAdd) return null;
    return (
      <>
        <ErrorNotice error={catalog.error} />
        {catalogReady ? (
          <p className="muted">
            No skills are installed. Add a SKILL.md under the configured skills
            directory to make one selectable.
          </p>
        ) : null}
      </>
    );
  }
  return (
    <>
      <ErrorNotice error={catalog.error} />
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a skill while the list is focused. Review instructions
        stays on the selected row. Skills do not grant tools.
        {onRemove
          ? " Remove stays on a skill missing from the catalog."
          : ""}
        {onAdd
          ? " Add stays on an installed catalog skill. At most four."
          : onRemove
            ? " Adding skills stays in Agents."
            : ""}{" "}
        There is no inspectable Skill Run.
      </p>
      <div
        ref={listRef}
        className="agent-choice-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {rows.map((skill, i) => {
          const current = i === index;
          const installedSkill = byId.has(skill.id);
          const attachedId = ids.includes(skill.id);
          const removable =
            !!onRemove && attachedId && catalogReady && !installedSkill;
          const canAdd = addable(skill) && !attachedId;
          const actionTab = active && current ? 0 : -1;
          const removeName = shortId
            ? `Remove skill ${skill.id} ${shortId}`
            : `Remove skill ${skill.id}`;
          const addName = shortId
            ? `Add skill ${skill.id} ${shortId}`
            : `Add skill ${skill.id}`;
          return (
            <div
              key={skill.id}
              aria-label={`Skill ${skill.name} ${skill.id}`}
              {...itemProps(i, skill.id)}
              tabIndex={active && current ? 0 : -1}
            >
              <div className="row spread">
                <div>
                  <p>
                    <strong>{skill.name}</strong>
                    {installedSkill ? (
                      <>
                        {" "}
                        <small>
                          {skill.id}
                          {skill.version ? ` ${skill.version}` : ""}
                          {skill.description ? `. ${skill.description}` : ""}
                          {skill.required_permissions.length
                            ? ` ${skill.required_permissions.join(", ")}`
                            : ""}
                        </small>
                      </>
                    ) : null}
                  </p>
                  {installedSkill ? (
                    <details className="agent-skill-text">
                      <summary
                        tabIndex={actionTab}
                      >{`Review ${skill.name} ${skill.id} instructions`}</summary>
                      <pre>{skill.instructions}</pre>
                    </details>
                  ) : catalogReady ? (
                    <p className="muted">Not in the installed catalog.</p>
                  ) : null}
                </div>
                {removable ? (
                  <Button
                    type="button"
                    variant="secondary"
                    tabIndex={actionTab}
                    disabled={disabled || pending}
                    aria-label={removeName}
                    onClick={() => onRemove?.(skill.id)}
                  >
                    Remove
                  </Button>
                ) : canAdd ? (
                  <Button
                    type="button"
                    variant="secondary"
                    tabIndex={actionTab}
                    disabled={disabled || pending}
                    aria-label={addName}
                    onClick={() => onAdd?.(skill.id)}
                  >
                    Add
                  </Button>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}
