import { useId, type KeyboardEvent } from "react";
import { useListKeyboard } from "./useListKeyboard";

export type ImageOperation = "t2i" | "img2img" | "recompose" | "upscale";

const OPERATIONS = [
  { key: "t2i" as const, title: "Generate" },
  { key: "img2img" as const, title: "Edit" },
  { key: "recompose" as const, title: "Recompose" },
  { key: "upscale" as const, title: "Upscale" },
];

export function ImageOperationChoiceList({
  value,
  onChange,
  disabled,
}: {
  value: ImageOperation;
  onChange: (mode: ImageOperation) => void;
  disabled?: boolean;
}) {
  const labelId = useId();
  const items = [...OPERATIONS];
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
    if (target.closest("a, textarea, summary, select")) return;
    if (event.key === " " && target.closest("input")) return;
    const item = items[index];
    if (!item || disabled) return;
    event.preventDefault();
    onChange(item.key);
  };
  return (
    <>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose an image operation while the list is focused. Space or
        Enter selects it. Enter does not queue a Run. Edit, Recompose and
        Upscale still use Qwen. There is no inspectable operation Run.
      </p>
      <div
        ref={listRef}
        className="mode-tabs image-operation-choice-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {items.map((item, i) => (
          <button
            key={item.key}
            type="button"
            aria-label={`Operation ${item.key}`}
            aria-pressed={value === item.key}
            disabled={disabled}
            {...itemProps(i, item.key)}
            onClick={() => onChange(item.key)}
          >
            {item.title}
          </button>
        ))}
      </div>
    </>
  );
}
