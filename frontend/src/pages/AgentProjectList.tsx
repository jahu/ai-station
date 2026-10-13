import { useId, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { useListKeyboard } from "./useListKeyboard";

export type LinkedProject = { id: string; name: string };

export function AgentProjectList({
  agentId,
  projectId,
  projects,
  tabIndex = 0,
  disabled = false,
  onSave,
}: {
  agentId: string;
  projectId: string | null;
  projects: LinkedProject[];
  tabIndex?: number;
  disabled?: boolean;
  onSave: (project_id: string | null) => void;
}) {
  const shortId = agentId.slice(0, 8);
  const labelId = useId();
  const items = [{ id: "", name: "No linked project" }, ...projects];
  const saved = projectId ?? "";
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    items,
    (item) => item.id || "none",
    { initialKey: saved || "none" },
  );
  const active = tabIndex >= 0;
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown(event);
    if (event.defaultPrevented) return;
    if (event.key !== " " && event.key !== "Enter") return;
    const target = event.target as HTMLElement;
    if (target.closest("a, button, textarea, input, summary, select")) return;
    const item = items[index];
    if (!item || disabled) return;
    event.preventDefault();
    const next = item.id || null;
    if (next === saved) return;
    onSave(next);
  };
  return (
    <>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a linked project while the list is focused. Space or
        Enter selects it. That tags this agent’s Runs for filtering. It does not
        grant coding, Git or repository access. There is no inspectable
        project-link Run.
      </p>
      <div
        ref={listRef}
        className="agent-choice-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {items.map((item, i) => {
          const current = i === index;
          const rowTab = active && current ? 0 : -1;
          const value = item.id || null;
          const name = item.id
            ? `Linked project ${item.id}`
            : `Linked project none ${shortId}`;
          return (
            <div
              key={item.id || "none"}
              aria-label={name}
              {...itemProps(i, item.id || "none")}
              tabIndex={rowTab}
            >
              <label className="agent-tool">
                <input
                  type="radio"
                  name={`linked_project_${shortId}`}
                  checked={saved === item.id}
                  disabled={disabled}
                  tabIndex={rowTab}
                  aria-label={name}
                  onChange={() => {
                    if (disabled || value === (projectId ?? null)) return;
                    onSave(value);
                  }}
                />
                <span>
                  <strong>{item.name}</strong>
                </span>
              </label>
            </div>
          );
        })}
      </div>
    </>
  );
}

export function AgentLinkedProjectLinks({
  agentId,
  projectId,
  projectName,
  tabIndex = 0,
}: {
  agentId: string;
  projectId: string | null;
  projectName?: string;
  tabIndex?: number;
}) {
  const shortId = agentId.slice(0, 8);
  const active = tabIndex >= 0;
  const taggedTo = projectId
    ? `/runs?project_id=${projectId}&agent_id=${agentId}`
    : `/runs?agent_id=${agentId}`;
  return (
    <p className="muted">
      {projectId ? (
        <>
          Linked project{" "}
          <Link
            className="text-link"
            to={`/projects/${projectId}`}
            tabIndex={active ? 0 : -1}
            aria-label={`Inspect project ${projectId}`}
          >
            {projectName || projectId}
          </Link>
          .{" "}
        </>
      ) : null}
      <Link
        className="text-link"
        to={taggedTo}
        tabIndex={active ? 0 : -1}
        aria-label={`View tagged Runs ${shortId}`}
      >
        View tagged Runs
      </Link>
      . That filter does not grant coding, Git or repository access.
    </p>
  );
}
