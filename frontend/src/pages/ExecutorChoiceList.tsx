import { useId, type KeyboardEvent } from "react";
import { useListKeyboard } from "./useListKeyboard";

export type CodingExecutorChoice = "auto" | "local" | "cursor" | "codex";

const EXECUTORS = [
  {
    key: "auto" as const,
    title: "Auto",
    detail:
      "Uses the project's preferred executor. Never a silent provider switch.",
  },
  {
    key: "local" as const,
    title: "Local AI",
    detail: "This conversation's local model in an owned worktree.",
  },
  {
    key: "cursor" as const,
    title: "Cursor",
    detail: "External AI. Requires explicit consent.",
  },
  {
    key: "codex" as const,
    title: "Codex",
    detail: "External AI. Requires explicit consent.",
  },
];

export function ExecutorChoiceList({
  value,
  onChange,
  disabled,
}: {
  value: CodingExecutorChoice;
  onChange: (choice: CodingExecutorChoice) => void;
  disabled?: boolean;
}) {
  const labelId = useId();
  const items = [...EXECUTORS];
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    items,
    (item) => item.key,
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
    onChange(item.key);
  };
  return (
    <>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a coding executor while the list is focused. Space or
        Enter selects it. Enter does not start a coding Run. Claude Code stays
        unavailable. There is no inspectable executor Run.
      </p>
      <div
        ref={listRef}
        className="executor-choice-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {items.map((item, i) => {
          const current = i === index;
          return (
            <div
              key={item.key}
              aria-label={`Executor ${item.key}`}
              {...itemProps(i, item.key)}
            >
              <label className="agent-tool">
                <input
                  type="radio"
                  name={labelId}
                  checked={value === item.key}
                  disabled={disabled}
                  tabIndex={current ? 0 : -1}
                  onChange={() => onChange(item.key)}
                />
                <span>
                  <strong>{item.title}</strong>
                  <small>{item.detail}</small>
                </span>
              </label>
            </div>
          );
        })}
      </div>
    </>
  );
}
