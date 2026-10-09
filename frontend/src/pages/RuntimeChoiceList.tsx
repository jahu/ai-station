import { useId, type KeyboardEvent } from "react";
import { useListKeyboard } from "./useListKeyboard";

export type OwnedRuntimeChoice = {
  id: string;
  name: string;
  status: string;
};

export function RuntimeChoiceList({
  instances,
  value,
  onChange,
  disabled,
}: {
  instances: OwnedRuntimeChoice[];
  value: string;
  onChange: (id: string) => void;
  disabled?: boolean;
}) {
  const labelId = useId();
  const items = [...instances];
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
        Arrow keys choose an owned llama.cpp instance while the list is focused.
        Space or Enter selects it. Enter does not send. External servers are not
        listed. There is no inspectable runtime-selection Run.
      </p>
      <div
        ref={listRef}
        className="runtime-choice-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {items.map((item, i) => {
          const current = i === index;
          return (
            <div
              key={item.id}
              aria-label={`Runtime ${item.id}`}
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
                  <small>{item.status}</small>
                </span>
              </label>
            </div>
          );
        })}
      </div>
    </>
  );
}
