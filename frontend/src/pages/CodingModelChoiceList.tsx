import { useId, type KeyboardEvent } from "react";
import { useListKeyboard } from "./useListKeyboard";

export type CodingModelChoice = { id: string; name: string };

const AUTO: CodingModelChoice = {
  id: "",
  name: "Auto — provider default",
};

export function CodingModelChoiceList({
  models,
  value,
  onChange,
  disabled,
}: {
  models: CodingModelChoice[];
  value: string;
  onChange: (id: string) => void;
  disabled?: boolean;
}) {
  const labelId = useId();
  const items = [
    AUTO,
    ...models.filter((model) => model.id && model.id !== "auto"),
  ];
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    items,
    (item) => item.id || "auto",
    { initialKey: value || "auto" },
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
  return (
    <>
      <p id={labelId} className="sr-only">
        Model choices. Use arrow keys to move, then Space or Enter to select.
      </p>
      <div
        ref={listRef}
        className="coding-model-choice-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {items.map((item, i) => {
          const current = i === index;
          const key = item.id || "auto";
          return (
            <div key={key} aria-label={`Model ${key}`} {...itemProps(i, key)}>
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
                  <small>
                    {item.id
                      ? "Installed CLI catalog"
                      : "Uses the selected provider’s default model."}
                  </small>
                </span>
              </label>
            </div>
          );
        })}
      </div>
    </>
  );
}
