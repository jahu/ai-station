import { useId, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { useListKeyboard } from "./useListKeyboard";

export type CodingProjectChoice = {
  id: string;
  name: string;
  preferred_executor?: string;
};

function preferredLabel(preferred?: string) {
  if (preferred === "cursor") return "Preferred executor: Cursor";
  if (preferred === "codex") return "Preferred executor: Codex";
  if (preferred === "local") return "Preferred executor: Local AI";
  return "No preferred executor";
}

export function ProjectChoiceList({
  projects,
  value,
  onChange,
  disabled,
}: {
  projects: CodingProjectChoice[];
  value: string;
  onChange: (id: string) => void;
  disabled?: boolean;
}) {
  const labelId = useId();
  const items = [...projects];
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    items,
    (item) => item.id,
    { initialKey: value },
  );
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown(event);
    if (event.defaultPrevented) return;
    if (event.key !== " " && event.key !== "Enter") return;
    const target = event.target as HTMLElement;
    if (target.closest("a, button, textarea, summary, select")) return;
    if (event.key === " " && target.closest("input")) return;
    const item = items[index];
    if (!item || disabled) return;
    event.preventDefault();
    onChange(item.id);
  };
  if (!items.length) return null;
  return (
    <>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a project while the list is focused. Space or Enter
        selects it. Inspect project and View tagged Runs stay on that row and do
        not start a coding Run. There is no inspectable project-selection Run.
      </p>
      <div
        ref={listRef}
        className="project-choice-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {items.map((item, i) => {
          const current = i === index;
          return (
            <div
              key={item.id}
              aria-label={`Project ${item.id}`}
              {...itemProps(i, item.id)}
            >
              <label className="agent-tool">
                <input
                  type="radio"
                  name={labelId}
                  checked={value === item.id}
                  disabled={disabled}
                  tabIndex={current ? 0 : -1}
                  onChange={() => onChange(item.id)}
                />
                <span>
                  <strong>{item.name}</strong>
                  <small>{preferredLabel(item.preferred_executor)}</small>
                </span>
              </label>
              <span>
                <Link
                  className="text-link"
                  to={`/projects/${item.id}`}
                  tabIndex={current ? 0 : -1}
                  aria-label={`Inspect project ${item.id}`}
                  onClick={(event) => event.stopPropagation()}
                >
                  Inspect project
                </Link>
                {" · "}
                <Link
                  className="text-link"
                  to={`/runs?project_id=${item.id}`}
                  tabIndex={current ? 0 : -1}
                  aria-label={`View tagged Runs ${item.id}`}
                  onClick={(event) => event.stopPropagation()}
                >
                  View tagged Runs
                </Link>
              </span>
            </div>
          );
        })}
      </div>
    </>
  );
}
