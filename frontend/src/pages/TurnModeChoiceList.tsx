import { useId, type KeyboardEvent } from "react";
import { useListKeyboard } from "./useListKeyboard";

export type TurnMode = "auto" | "local" | "orchestrator";

export function TurnModeChoiceList({
  value,
  orchestrator,
  onChange,
  disabled,
}: {
  value: TurnMode;
  orchestrator: boolean;
  onChange: (mode: TurnMode) => void;
  disabled?: boolean;
}) {
  const labelId = useId();
  const items = [
    {
      key: "auto" as const,
      title: `Conversation default (${orchestrator ? "Platform assistant" : "Conversation only"})`,
      detail: "Uses the saved conversation mode. Settings stay unchanged.",
    },
    {
      key: "local" as const,
      title: "Conversation only",
      detail: "This turn stays a local chat reply.",
    },
    {
      key: "orchestrator" as const,
      title: "Platform assistant",
      detail: "This turn can route to owned station actions.",
    },
  ];
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
        Arrow keys choose this turn's execution mode while the list is focused.
        Space or Enter selects it. Enter does not send. The saved conversation
        mode is not rewritten. There is no inspectable turn-mode Run.
      </p>
      <div
        ref={listRef}
        className="turn-choice-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {items.map((item, i) => {
          const current = i === index;
          return (
            <div
              key={item.key}
              aria-label={`Turn ${item.key}`}
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
