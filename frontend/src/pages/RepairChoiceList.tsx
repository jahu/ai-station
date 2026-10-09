import { useId, type KeyboardEvent } from "react";
import { useListKeyboard } from "./useListKeyboard";

const REPAIR_BUDGETS = [
  {
    key: 0,
    title: "Off — ask me first",
    detail: "I will request repairs after failed checks.",
  },
  {
    key: 1,
    title: "One attempt",
    detail: "Same local model, files and saved checks.",
  },
  {
    key: 2,
    title: "Up to two attempts",
    detail: "Commit still requires your review.",
  },
] as const;

export function RepairChoiceList({
  value,
  onChange,
  disabled,
}: {
  value: number;
  onChange: (attempts: number) => void;
  disabled?: boolean;
}) {
  const labelId = useId();
  const items = [...REPAIR_BUDGETS];
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    items,
    (item) => String(item.key),
    { initialKey: String(value) },
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
        Arrow keys choose a repair budget while the list is focused. Space or
        Enter selects it. Enter does not start a coding Run. There is no
        inspectable repair-budget Run.
      </p>
      <div
        ref={listRef}
        className="repair-choice-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {items.map((item, i) => {
          const current = i === index;
          return (
            <div
              key={item.key}
              aria-label={`Repair ${item.key}`}
              {...itemProps(i, String(item.key))}
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
