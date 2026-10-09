import { useId, type KeyboardEvent } from "react";
import { useListKeyboard } from "./useListKeyboard";

export type ImageBackend = "qwen" | "juggernaut";

const BACKENDS = [
  {
    key: "qwen" as const,
    title: "Qwen",
    detail: "Existing pipeline. Seed and negative prompt stay hidden.",
  },
  {
    key: "juggernaut" as const,
    title: "Juggernaut",
    detail:
      "Seed and negative prompt are available. Missing weights fail closed.",
  },
];

export function ImageBackendChoiceList({
  value,
  onChange,
  disabled,
}: {
  value: ImageBackend;
  onChange: (backend: ImageBackend) => void;
  disabled?: boolean;
}) {
  const labelId = useId();
  const items = [...BACKENDS];
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
        Arrow keys choose a Generate backend while the list is focused. Space or
        Enter selects it. Enter does not queue a Run. There is no inspectable
        backend Run.
      </p>
      <div
        ref={listRef}
        className="image-backend-choice-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {items.map((item, i) => {
          const current = i === index;
          return (
            <div
              key={item.key}
              aria-label={`Backend ${item.key}`}
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
