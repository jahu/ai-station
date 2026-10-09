import { useId, type KeyboardEvent } from "react";
import { useListKeyboard } from "./useListKeyboard";

export type GgufChoice = { id: string; name: string };

export function GgufChoiceList({
  models,
  value,
  onChange,
  disabled,
}: {
  models: GgufChoice[];
  value: string;
  onChange: (id: string) => void;
  disabled?: boolean;
}) {
  const labelId = useId();
  const items = [...models];
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
        Arrow keys choose a discovered GGUF while the list is focused. Space or
        Enter selects it. Enter does not send. External runtimes are not listed.
        There is no inspectable GGUF-selection Run.
      </p>
      <div
        ref={listRef}
        className="gguf-choice-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {items.map((item, i) => {
          const current = i === index;
          return (
            <div
              key={item.id}
              aria-label={`GGUF ${item.id}`}
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
                  <small>Discovered language-model GGUF</small>
                </span>
              </label>
            </div>
          );
        })}
      </div>
    </>
  );
}
